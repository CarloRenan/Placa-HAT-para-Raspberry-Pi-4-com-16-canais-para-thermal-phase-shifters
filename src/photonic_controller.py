import spidev
import time
import struct
import threading
import RPi.GPIO as GPIO

class PhotonicControllerHAT:
    """
    Abstração sistêmica da Placa HAT responsável por acionar matrizes fotônicas.
    Interfaces lógicas gerenciam a carga SPI de 24-bit no DAC AD5391 (Canais 0-15)
    e a captura contínua nos chips ADC para instrumentação do sensoriamento.
    """

    # --- Constantes do Hardware Físico ---
    PIN_CLR = 22       # Pino Clear assíncrono (Derrubada Global)
    PIN_LDAC = 27      # Pino de Transferência/Atualização Síncrona do Latch 
    PIN_RESET = 17     # Pino para HW Reset das condições de falha

    MAX_VOLTAGE = 3.3  # Limite máximo de excursão dos buffers RRIO (V)
    MAX_MA_PER_CH = 45.5 # Fronteira nominal de potência na fotônica (mA)
    
    # Derivados da calibração do INA180A2 (Gain = 50 V/V) e Shunt R=1 Ohm
    INA_GAIN = 50.0 
    R_SHUNT = 1.0

    def __init__(self):
        """
        Inicializador construtivo dos GPIOs da placa HAT e 
        das instâncias virtuais do barramento do Kernel Linux (spidev).
        """
        self._setup_gpio_state()
        self._init_spi_interfaces()
        self._perform_hardware_reset()

        # Flags de contenção térmica
        self.system_running = True

        # Inicia a Thread Assíncrona dedicada exclusivamente para 
        # proteção contra sobrecorrentes (Supervisório Daemonizado).
        self.watcher_thread = threading.Thread(target=self._current_watchdog_loop, daemon=True)
        self.watcher_thread.start()

    def _setup_gpio_state(self):
        """ Eleva os pinos lógicos auxiliares e desativa funções disruptivas """
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        # Níveis altos inativam as ações destrutivas (Active Low)
        GPIO.setup(self.PIN_CLR, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.PIN_LDAC, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.PIN_RESET, GPIO.OUT, initial=GPIO.HIGH)

    def _init_spi_interfaces(self):
        """ 
        Configura o Barramento SPI principal (SPI0) direcionado ao DAC de forma 
        dedicada, garantindo taxas ultra-rápidas de comutação dos registros. 
        O Barramento auxiliar (SPI1) rastreia a aquisição diferencial (ADC).
        """
        self.spi_dac = spidev.SpiDev()
        self.spi_dac.open(0, 0) # SPI0, CE0
        # Tolerância a 20MHz do protocolo AD5391; CPOL=0 CPHA=1 (Mode 1 ou 2)
        self.spi_dac.max_speed_hz = 15000000 
        self.spi_dac.mode = 0b01 # Clock Phase Mode compatível

        # ADC via SPI secundário. Modulação suave para amostragens em kSPS.
        self.spi_adc = spidev.SpiDev()
        self.spi_adc.open(1, 0) # SPI1, CE0
        self.spi_adc.max_speed_hz = 1200000

    def _perform_hardware_reset(self):
        """ Gatilha o Pino Físico cravando o AD5391 em modo nominal nulo. """
        GPIO.output(self.PIN_RESET, GPIO.LOW)
        time.sleep(0.02) # Atrasa no pulso HW (Setup Time)
        GPIO.output(self.PIN_RESET, GPIO.HIGH)
        time.sleep(0.01)

    def trigger_sync_update(self):
        """
        Comuta as tensões do Registrador de Background para a porta física 
        simultaneamente, eliminando transientes de desbalanceamento na fotônica.
        """
        GPIO.output(self.PIN_LDAC, GPIO.LOW)
        time.sleep(0.001)
        GPIO.output(self.PIN_LDAC, GPIO.HIGH)

    def trigger_emergency_clamp(self):
        """ Zera o potencial de tensão de forma bruta e instantânea nas linhas. """
        print("\n[!] ATENÇÃO: OVERRIDE LÓGICO DETECTADO. LIMPANDO MATRIZ ANALÓGICA.")
        GPIO.output(self.PIN_CLR, GPIO.LOW)
        time.sleep(0.005)
        GPIO.output(self.PIN_CLR, GPIO.HIGH)

    def set_voltage(self, channel: int, voltage: float):
        """
        Mapeia a solicitação decimal escalar de Tensão em Volts para um 
        quadro binário contínuo de 24-bits interpretado pelo CI AD5391.
        """
        if not (0 <= channel <= 15):
            raise ValueError("Falha no Mapeamento do Canal (0 a 15).")

        voltage = max(0.0, min(self.MAX_VOLTAGE, voltage))

        # A transferência nominal VOUT baseia-se num espectro VREF escalonado.
        # Considerando a referência local em 1.65V e buffer nativo de ganho x2.
        # Quantização absoluta: 12-bits = 4096 passos
        code = int((voltage / self.MAX_VOLTAGE) * 4095)
        
        # Constrói o Frame de 24 Bits (Byte 1)
        # Seguido pelas flags (Byte 2)
        # E remanescente (Byte 3)
        
        byte_1 = channel & 0x0F
        
        # Inserção das flags 1,1 (binário 11000000 = 0xC0) combinada a metade do DAC
        reg_flags = 0xC0 
        data_upper_6 = (code >> 6) & 0x3F
        byte_2 = reg_flags | data_upper_6
        
        data_lower_6 = (code & 0x3F) << 2
        byte_3 = data_lower_6

        frame = [byte_1, byte_2, byte_3]
        
        # Envia de forma atômica para o barramento SPI local
        self.spi_dac.xfer3(frame)

    def get_measured_current_ma(self, channel: int) -> float:
        """
        Lê e decodifica a tensão transladada proveniente dos Chips INA180A2.
        Suposição de um MCP3008 de 10 Bits em malha fechada.
        """
        # Comando Singe-Ended pro MCP3008 via SPI
        comando_spi = 0x80 | (channel << 4)
        resposta = self.spi_adc.xfer2([1, comando_spi, 0])
        raw_adc = ((resposta & 0x03) << 8) | resposta

        v_adc_lido = (raw_adc / 1023.0) * self.MAX_VOLTAGE
        
        # A corrente base provém da divisão da leitura pelo fator dos Buffers.
        corrente_amperes = v_adc_lido / (self.INA_GAIN * self.R_SHUNT)
        return corrente_amperes * 1000.0 # Transposição escalar para miliamperes

    def _current_watchdog_loop(self):
        """
        Fio de execução autônomo. Rastreia exaustivamente os canais e
        imputa bloqueio caso as densidades extrapolem a banda estipulada.
        """
        while self.system_running:
            for ch in range(16):
                corrente_ma = self.get_measured_current_ma(ch)
                if corrente_ma > self.MAX_MA_PER_CH:
                    print(f"\n!!! SOBRECARGA DETECTADA! CANAL {ch} LEU {corrente_ma:.1f} mA!!!")
                    self.trigger_emergency_clamp()
                    # Bloqueio protetivo para forçar o decaimento termodinâmico
                    time.sleep(2.0)
            time.sleep(0.01)

    def terminate_operations(self):
        """ Desmontagem dos artefatos Python e limpeza dos pinos """
        self.system_running = False
        self.trigger_emergency_clamp()
        self.spi_dac.close()
        self.spi_adc.close()
        GPIO.cleanup()


if __name__ == "__main__":
    controller = PhotonicControllerHAT()
    print("==============================================")
    print("   Módulo Interativo de Controle HAT INICIADO ")
    print("==============================================")
    
    try:
        while True:
            print("\n--- Configuração de Saída Analógica ---")
            canal_str = input("Digite o número do CANAL (0 a 15) ou 'sair' para encerrar: ")
            
            # Condição de saída do programa
            if canal_str.strip().lower() == 'sair':
                break
            
            # Validação do Canal
            try:
                canal = int(canal_str)
                if not (0 <= canal <= 15):
                    print("Erro: O canal deve estar estritamente entre 0 e 15.")
                    continue
            except ValueError:
                print("Erro: Entrada inválida. Digite um número inteiro para o canal.")
                continue
                
            # Validação da Tensão
            tensao_str = input(f"Digite a TENSÃO desejada para o Canal {canal} (0.0 a 3.3 V): ")
            try:
                tensao = float(tensao_str.replace(',', '.'))
                if not (0.0 <= tensao <= 3.3):
                    print("Erro: A tensão ultrapassa os limites seguros (0.0 a 3.3 V).")
                    continue
            except ValueError:
                print("Erro: Entrada inválida. Digite um número decimal para a tensão.")
                continue
            
            # Grava a tensão na memória do DAC (ainda não altera a saída física)
            controller.set_voltage(canal, tensao)
            print(f"-> Tensão de {tensao:.2f}V registrada na memória do Canal {canal}.")
            
            # O usuário escolhe quando acionar o pino de sincronização (LDAC)
            aplicar = input("Deseja aplicar fisicamente as tensões pendentes nos canais agora? (s/n): ")
            
            if aplicar.strip().lower() == 's':
                controller.trigger_sync_update()
                print(">>> Atualização Síncrona Disparada! As tensões estão ativas nas saídas.")
                
                # Leitura instantânea por telemetria para verificação rápida
                time.sleep(0.1) # Aguarda um breve momento para estabilização térmica e elétrica
                corrente_atual = controller.get_measured_current_ma(canal)
                print(f" >> Diagnóstico: O Canal {canal} está drenando aproximadamente {corrente_atual:.2f} mA.")
            else:
                print(">>> As tensões permanecem pendentes na memória. Configure outros canais se desejar.")

    except KeyboardInterrupt:
        print("\nSinal interativo (CTRL+C) processado pelo usuário.")
    finally:
        print("Encerrando operações e zerando as saídas de tensão para segurança...")
        controller.terminate_operations()
        print("Sistema desligado com sucesso.")
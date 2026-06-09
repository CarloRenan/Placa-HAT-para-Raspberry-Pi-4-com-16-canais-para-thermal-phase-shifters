# Placa-HAT-para-Raspberry-Pi-4-com-16-canais-para-thermal-phase-shifters

# Raspberry Pi 4 Photonic HAT Controller

Este repositório contém a documentação, esquemáticos e o software de controle para um HAT customizado de sinais mistos projetado para a Raspberry Pi 4. O sistema é focado no acionamento de matrizes fotônicas e condicionamento de sinais analógicos de alta precisão.

## 🧠 Arquitetura de Hardware

A rede de distribuição de energia e controle foi rigorosamente dimensionada para garantir integridade de sinal:
* [cite_start]**Conversão de Energia Principal:** Utiliza o conversor buck síncrono AP63205WU-7, reduzindo a tensão de entrada para um barramento regulado de 5V com capacidade de 2A[cite: 4, 28].
* [cite_start]**Regulação Secundária (LDO):** Um AP2112K-3.3TRG1 fornece uma rede isolada de 3,3V dedicada aos circuitos digitais e analógicos sensíveis[cite: 68].
* [cite_start]**Conversão Digital-Analógica (DAC):** Implementada através do AD5391 (matriz multicanal), orquestrando a geração precisa dos sinais a partir da rede filtrada de 3,3V[cite: 30, 99].
* [cite_start]**Condicionamento Analógico:** Matriz em cascata utilizando 4 CIs TLV2464 (totalizando 16 canais de amplificadores operacionais *rail-to-rail*), alimentados diretamente pelo barramento robusto de 5V[cite: 13, 29].

## 💻 Software de Controle

Localizado na pasta `/src`, o script Python (`photonic_controller.py`) estabelece uma abstração sistêmica da placa. 
* Comunicação em altíssima velocidade (15 MHz) via barramento SPI dedicado (SPI0) para o DAC AD5391.
* Monitoramento autônomo via thread secundária para ler a transposição diferencial dos sensores INA180A2 (SPI1).
* Gatilhos emergenciais de contenção térmica via pinagem GPIO (Clear assíncrono).

## 📂 Estrutura do Repositório

* `/docs`: Relatórios de viabilidade eletrotérmica e esquemáticos da placa.
* `/hardware`: Arquivos fonte da PCB.
* `/src`: Driver e interface de linha de comando em Python.

## 👨‍💻 Autor
**Carlos Renan** - Engenheiro Eletricista


<img width="1216" height="873" alt="1781029299632" src="https://github.com/user-attachments/assets/6939fe73-80a4-4442-b4bd-ae4658c0456b" />


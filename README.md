# SysMon — widget de sistema para Omarchy/Quickshell

Widget transparente na barra com CPU, GPU, RAM, disco, rede e temperatura, mais
uma limpeza automática de disco e um **relatório diário do sistema por e-mail**
que ainda tenta **corrigir sozinho** os serviços do usuário que falharam.

![Quickshell](https://img.shields.io/badge/Quickshell-QML-blue) ![Python](https://img.shields.io/badge/python-3.x-informational)

## Como funciona

```
poller.py  ──JSON──▶  SysMon.qml          widget (repolla a cada 10 s)
     │
     └─▶ relatorio.py  ──SMTP──▶  você     relatório 10h/18h
              │
              └─▶ systemctl  ─────────▶  tenta reiniciar unidades que falharam

limpar.sh  ──────────────────────────▶  lixeira, /tmp, cache, journal
```

- **`poller.py`** é um processo curto que   **imprime JSON e sai** — o QML o invoca
  via `Process` e lê a saída. Nada fica rodando em background, o que evita
  consumo de CPU e o problema clássico de "processo do widget virou leak".
- **CPU e rede** são derivadas de **diferença** entre leituras: o `/proc/stat` e
  os contadores de byte são lidos, guardados em `~/.local/state/sysmon/`, e a
  taxa vem do intervalo. Por isso o primeiro poll mostra `—` em vez de número
  inventado.
- **Teste de velocidade** é refeito só a cada 30 min (`SPEED_MAX_AGE`), porque
  é a única coleta cara do conjunto.
- **`relatorio.py`** numera os erros do journal por *assinatura* (para o mesmo
  erro repetido virar uma linha só), tenta reiniciar/resetar unidades de usuário
  que falharam, e manda o resultado por e-mail.

## Instalação

```bash
cp credenciais.env.example credenciais.env
chmod 600 credenciais.env
$EDITOR credenciais.env            # GMAIL_ADDR / GMAIL_PASS (senha de app)

# plugin (diretório de plugin do Omarchy)
mkdir -p ~/.config/omarchy/plugins/sysmon
cp poller.py relatorio.py SysMon.qml limpar.sh manifest.json \
   ~/.config/omarchy/plugins/sysmon/

# relatório diário
cp sysmon-relatorio.service sysmon-relatorio.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now sysmon-relatorio.timer
```

O `.env` do relatório é lido por padrão do mesmo arquivo do projeto
**leitormail-postits** (também deste autor); aponte para outro com
`SYSMON_ENV=/caminho/credenciais.env`.

## Variáveis

| Onde | Chave | Padrão | Para quê |
|---|---|---|---|
| `credenciais.env` | `GMAIL_ADDR` / `GMAIL_PASS` | — | envio do relatório (senha de **app**) |
| ambiente | `SYSMON_ENV` | o do LeitorMail | caminho alternativo do `.env` |
| `SysMon.qml` | `pollIntervalMs` | `10000` | intervalo do widget |

## Por que "imprimir JSON e sair"

Um `Process` do Quickshell que termina devolve `stdout` e um código de saída
limpo. Um processo permanente exigiria reiniciar o shell inteiro para mudar
lógica, e nada garantiria que ele morreu quando o widget saiu. O custo de
`fork + import + leitura de /proc` é pequeno comparado a manter um daemon vivo
só para o widget.

## Requisitos

- Quickshell (Omarchy já traz)
- `lm_sensors` para as temperaturas
- `systemd` (unidades de usuário) para o relatório e a limpeza

import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons

Item {
  id: root

  readonly property string home: Quickshell.env("HOME")
  readonly property string pluginDir: home + "/.config/omarchy/plugins/sysmon"

  property int pollIntervalMs: 10000
  property var data: null
  property string statusText: "verificando..."
  property string cleanText: ""

  readonly property int gadgetW: 272
  readonly property int gadgetH: 206

  // Contorno escuro no texto para leitura sobre qualquer fundo de tela
  readonly property color textStyleColor: Util.alpha("#000000", 0.55)
  readonly property int textOutline: Text.Outline

  function poll() {
    if (pollProc.running) return
    pollProc.running = true
  }

  function applyResult(raw) {
    var text = String(raw || "").trim()
    if (!text) {
      statusText = "sem resposta"
      return
    }
    try {
      root.data = JSON.parse(text)
      var ativos = root.data.errors || 0
      if (ativos > 0) statusText = ativos + " erro" + (ativos > 1 ? "s" : "")
      else if ((root.data.err_avisos || 0) > 0) statusText = "ok · apenas avisos"
      else statusText = "ok"
    } catch (e) {
      statusText = "resposta inválida"
      root.data = null
    }
  }

  function fmtGb(mb) { return (mb / 1024).toFixed(1) }

  Timer {
    id: pollTimer
    interval: root.pollIntervalMs
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.poll()
  }

  Process {
    id: pollProc
    command: ["/usr/bin/python3", root.pluginDir + "/poller.py"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyResult(text)
    }
  }

  Process {
    id: cleanProc
    command: ["/bin/bash", root.pluginDir + "/limpar.sh"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.cleanText = "Limpeza concluída · " + new Date().toLocaleTimeString(Qt.locale(), "HH:mm")
    }
  }

  Variants {
    model: Quickshell.screens

    PanelWindow {
      id: gadget
      required property var modelData
      screen: modelData

      implicitWidth: root.gadgetW
      implicitHeight: root.gadgetH

      WlrLayershell.namespace: "sysmon"
      WlrLayershell.layer: WlrLayer.Bottom
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
      WlrLayershell.exclusionMode: ExclusionMode.Ignore

      anchors.bottom: true
      anchors.right: true

      margins {
        bottom: 16
        right: 16
      }

      // Fundo 100% transparente — nada esconde o papel de parede.
      // O texto usa contorno escuro para continuar legível no claro.

      Column {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 5

        Row {
          width: parent.width
          height: 17
          spacing: 6

          Rectangle {
            width: 8
            height: 8
            radius: 4
            anchors.verticalCenter: parent.verticalCenter
            color: Color.accent
          }

          Text {
            text: "SYS"
            color: Color.accent
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            style: root.textOutline
            styleColor: root.textStyleColor
            anchors.verticalCenter: parent.verticalCenter
          }

          Text {
            text: root.statusText
            color: root.statusText === "ok" || root.statusText.indexOf("ok") === 0
                   ? Color.accent : Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            style: root.textOutline
            styleColor: root.textStyleColor
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 110
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
          }
        }

        Grid {
          width: parent.width
          columns: 2
          columnSpacing: 12
          rowSpacing: 5

          Repeater {
            model: root.data ? [
              { label: "CPU",  value: v(root.data.cpu_temp) + "°C  ·  " + v(root.data.cpu_pct) + "%", color: Color.foreground },
              { label: "RAM",  value: fmtGb(v(root.data.ram ? root.data.ram.used_mb : 0)) + "G / " + fmtGb(v(root.data.ram ? root.data.ram.total_mb : 0)) + "G  (" + v(root.data.ram ? root.data.ram.pct : 0) + "%)", color: Color.foreground },
              { label: "DISK", value: v(root.data.disk ? root.data.disk.used_gb : 0) + "G / " + v(root.data.disk ? root.data.disk.total_gb : 0) + "G  (" + v(root.data.disk ? root.data.disk.pct : 0) + "%)", color: Color.foreground },
              { label: "GPU",  value: (root.data.gpu ? v(root.data.gpu.temp) + "°C  ·  " + v(root.data.gpu.util) + "%" : "—"), color: Color.foreground }
            ] : [
              { label: "CPU",  value: "—", color: Color.muted },
              { label: "RAM",  value: "—", color: Color.muted },
              { label: "DISK", value: "—", color: Color.muted },
              { label: "GPU",  value: "—", color: Color.muted }
            ]

            Row {
              required property var modelData
              width: parent.width
              spacing: 6

              Text {
                text: modelData.label
                width: 38
                color: Util.alpha(Color.accent, 0.9)
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                font.bold: true
                style: root.textOutline
                styleColor: root.textStyleColor
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                text: modelData.value
                color: modelData.color
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                style: root.textOutline
                styleColor: root.textStyleColor
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 44
                elide: Text.ElideRight
              }
            }
          }
        }

        Row {
          width: parent.width
          spacing: 6
          Text {
            text: "NET"
            width: 38
            color: Util.alpha(Color.accent, 0.9)
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            style: root.textOutline
            styleColor: root.textStyleColor
            anchors.verticalCenter: parent.verticalCenter
          }
          Text {
            text: root.data ? "↓ " + fmtMbps(root.data.net_down) + "   ↑ " + fmtMbps(root.data.net_up) + " Mbps" : "—"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            style: root.textOutline
            styleColor: root.textStyleColor
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 44
            elide: Text.ElideRight
          }
        }

        Row {
          width: parent.width
          spacing: 6
          Text {
            text: "TEST"
            width: 38
            color: Util.alpha(Color.accent, 0.9)
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            style: root.textOutline
            styleColor: root.textStyleColor
            anchors.verticalCenter: parent.verticalCenter
          }
          Text {
            text: root.data ? "↓ " + fmtMbps(root.data.speed_down) + "   ↑ " + fmtMbps(root.data.speed_up) + fmtAge(root.data.speed_age_s) : "—"
            color: Util.alpha(Color.foreground, 0.92)
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            style: root.textOutline
            styleColor: root.textStyleColor
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 44
            elide: Text.ElideRight
          }
        }

        Rectangle {
          width: parent.width
          height: 3
          radius: 1.5
          color: Util.alpha(Color.foreground, 0.22)

          Rectangle {
            width: parent.width * (root.data && root.data.disk ? root.data.disk.pct / 100.0 : 0)
            height: parent.height
            radius: 1.5
            color: Color.accent
          }
        }

        Row {
          width: parent.width
          height: 22
          spacing: 6

          Rectangle {
            id: btn
            width: 86
            height: 22
            radius: Style.cornerRadius
            color: Util.alpha(Color.accent, 0.9)
            border.color: Util.alpha(Color.foreground, 0.25)
            border.width: 1

            Text {
              text: "Limpar"
              anchors.centerIn: parent
              color: "#101418"
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }

            MouseArea {
              anchors.fill: parent
              onClicked: {
                root.cleanText = "Limpando..."
                cleanProc.running = true
              }
            }
          }

          Text {
            text: root.cleanText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            style: root.textOutline
            styleColor: root.textStyleColor
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 92
            elide: Text.ElideRight
          }
        }
      }

      function v(x) { return x === null || x === undefined ? (isNaN(x) ? "—" : x) : (typeof x === "string" ? x : x) }

      function fmtMbps(x) {
        if (x === null || x === undefined || isNaN(x)) return "—"
        return x < 10 ? x.toFixed(2) : x.toFixed(1)
      }

      function fmtAge(s) {
        if (s === null || s === undefined) return ""
        if (s < 90) return "   · agora"
        if (s < 3600) return "   · " + Math.round(s / 60) + " min"
        return "   · " + Math.round(s / 3600) + " h"
      }
    }
  }
}
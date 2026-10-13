import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.felipeoliboni.omarchy-redmibuds"
  ipcTarget: "io.github.felipeoliboni.omarchy-redmibuds"

  readonly property string address: setting("address", "")
  readonly property int channel: Number(setting("channel", 29))
  readonly property int pollInterval: Number(setting("pollInterval", 30))

  property bool connected: false
  property var leftBattery: null
  property var rightBattery: null
  property var caseBattery: null

  readonly property string scriptPath: {
    var url = String(Qt.resolvedUrl("scripts/redmi_buds_battery.py"))
    return url.indexOf("file://") === 0 ? url.substring(7) : url
  }

  readonly property string barLabel: {
    if (!connected) return "--"
    var l = leftBattery ? leftBattery.level : null
    var r = rightBattery ? rightBattery.level : null
    if (l === null && r === null) return "--"
    if (l === null) return r + "%"
    if (r === null) return l + "%"
    return Math.min(l, r) + "%"
  }

  function fraction(b) {
    return b ? Math.max(0, Math.min(1, b.level / 100)) : 0
  }

  function percentText(b) {
    return b ? (b.level + "%") : "—"
  }

  // Optimistic local selection only — the earbuds don't ack this command,
  // so this reflects "last mode we sent", not a confirmed device readback.
  property int ancMode: -1

  function sendAncMode(mode) {
    root.ancMode = mode
    if (mode === 0) ancOffProc.running = true
    else if (mode === 1) ancTransparencyProc.running = true
    else if (mode === 2) ancNoiseCancelProc.running = true
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: proc
    command: ["python3", root.scriptPath, root.address, "--channel", String(root.channel), "--loop", String(root.pollInterval)]
    running: root.address !== ""
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) {
        try {
          var data = JSON.parse(line)
          root.connected = !!data["connected"]
          root.leftBattery = data["left"] || null
          root.rightBattery = data["right"] || null
          root.caseBattery = data["case"] || null
        } catch (e) {
          // ignore malformed lines
        }
      }
    }
  }

  Process {
    id: ancOffProc
    command: ["python3", root.scriptPath, root.address, "--channel", String(root.channel), "--set-anc", "0"]
  }
  Process {
    // Empirically, on this 6 Lite unit wire-byte 2 produces real transparency
    // (swapped vs. the 5 Pro's own app convention this protocol was ported from).
    id: ancTransparencyProc
    command: ["python3", root.scriptPath, root.address, "--channel", String(root.channel), "--set-anc", "2"]
  }
  Process {
    // Empirically, wire-byte 1 produces real noise cancellation here.
    id: ancNoiseCancelProc
    command: ["python3", root.scriptPath, root.address, "--channel", String(root.channel), "--set-anc", "1"]
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    slotSize: Style.bar.statusSlot
    active: root.connected
    tooltipText: root.address === "" ? "Redmi Buds: set the MAC address in plugin settings"
      : (root.connected ? ("Redmi Buds · " + root.barLabel) : "Redmi Buds: disconnected")
    onPressed: function(b) { root.toggle() }

    iconComponent: Component {
      Item {
        implicitWidth: 16
        implicitHeight: 16
        readonly property color iconColor: button.active && button.useActiveColor ? button.activeColor : button.foreground

        Row {
          anchors.centerIn: parent
          spacing: 3

          Repeater {
            model: 2
            delegate: Column {
              spacing: 0
              Rectangle {
                width: 7
                height: 7
                radius: 3.5
                color: iconColor
                anchors.horizontalCenter: parent.horizontalCenter
              }
              Rectangle {
                width: 2
                height: 8
                radius: 1
                color: iconColor
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.horizontalCenterOffset: index === 0 ? -1 : 1
              }
            }
          }
        }
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(300))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(16)

        // ---------- Header ----------
        Item {
          width: parent.width
          implicitHeight: headerTitle.implicitHeight

          Text {
            id: headerTitle
            textFormat: Text.PlainText
            text: "🎧  Redmi Buds 6 Lite"
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Text {
            textFormat: Text.PlainText
            text: root.connected ? "CONNECTED" : "DISCONNECTED"
            color: root.connected
              ? Qt.darker(root.bar ? root.bar.foreground : Color.foreground, 1.1)
              : Color.urgent
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.0
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        // ---------- Section label ----------
        Text {
          textFormat: Text.PlainText
          text: "BATTERY"
          color: Qt.darker(root.bar ? root.bar.foreground : Color.foreground, 1.4)
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 1.2
        }

        // ---------- Battery rows ----------
        Column {
          width: parent.width
          spacing: Style.space(10)

          Repeater {
            model: [
              { label: "Left", battery: root.leftBattery },
              { label: "Right", battery: root.rightBattery },
              { label: "Case", battery: root.caseBattery }
            ]

            delegate: Item {
              width: column.width
              implicitHeight: Style.space(20)

              Text {
                id: rowLabel
                textFormat: Text.PlainText
                text: modelData.label
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.body
                width: Style.space(48)
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                id: rowStatus
                textFormat: Text.PlainText
                text: !modelData.battery
                  ? (modelData.label === "Case" ? "not in case" : "—")
                  : root.percentText(modelData.battery) + (modelData.battery.charging ? " ⚡" : "")
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.body
                horizontalAlignment: Text.AlignRight
                width: Style.space(84)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
              }

              Item {
                id: barTrackHolder
                anchors.left: rowLabel.right
                anchors.leftMargin: Style.space(8)
                anchors.right: rowStatus.left
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                height: Style.space(8)

                Rectangle {
                  id: track
                  anchors.fill: parent
                  radius: height / 2
                  color: Qt.rgba(
                    (root.bar ? root.bar.foreground.r : Color.foreground.r),
                    (root.bar ? root.bar.foreground.g : Color.foreground.g),
                    (root.bar ? root.bar.foreground.b : Color.foreground.b),
                    0.12)
                }

                Rectangle {
                  anchors.left: track.left
                  anchors.verticalCenter: track.verticalCenter
                  height: track.height
                  radius: track.radius
                  color: root.bar ? root.bar.foreground : Color.foreground
                  width: Math.max(modelData.battery ? track.height : 0, track.width * root.fraction(modelData.battery))

                  Behavior on width { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
                }
              }
            }
          }
        }

        // ---------- Listening mode ----------
        Text {
          textFormat: Text.PlainText
          text: "LISTENING MODE"
          color: Qt.darker(root.bar ? root.bar.foreground : Color.foreground, 1.4)
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 1.2
        }

        Column {
          width: parent.width
          spacing: 0

          Repeater {
            model: [
              { mode: 1, label: "Transparency" },
              { mode: 2, label: "Noise Cancellation" },
              { mode: 0, label: "Off" }
            ]

            delegate: Item {
              width: column.width
              implicitHeight: Style.space(30)

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.sendAncMode(modelData.mode)
              }

              Text {
                textFormat: Text.PlainText
                text: modelData.label
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.body
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                textFormat: Text.PlainText
                visible: root.ancMode === modelData.mode
                text: "✓"
                color: root.bar ? root.bar.foreground : Color.foreground
                font.pixelSize: Style.font.body
                font.bold: true
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }
        }

        Text {
          textFormat: Text.PlainText
          text: "Experimental: sent over the Redmi Buds 5 Pro protocol: not confirmed to physically change noise filtering on the 6 Lite."
          wrapMode: Text.WordWrap
          width: parent.width
          color: Qt.darker(root.bar ? root.bar.foreground : Color.foreground, 1.5)
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}

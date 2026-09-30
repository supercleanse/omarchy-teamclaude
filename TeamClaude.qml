import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as UI

Column {
  id: root
  spacing: Style.space(6)
  property string expandedAccount: ""
  property bool showHelp: false
  property bool polling: false
  property bool monitoring: true
  property var snapshotData: ({online: false, accounts: [], meters: [], lines: []})
  property string message: ""
  property bool failed: false
  property string pendingRemove: ""
  property string pendingOrg: ""
  property bool followLog: true
  property bool pausedLog: false
  property string consoleText: ""
  property double now: Date.now()
  readonly property string helper: Qt.resolvedUrl("teamclaude_bridge.py").toString().replace(/^file:\/\//, "")
  readonly property bool busy: operation.running
  readonly property color fg: Color.foreground
  readonly property color muted: Qt.darker(fg, 1.5)
  readonly property bool online: snapshotData.online === true

  function refresh() {
    if (monitoring && !poll.running) poll.running = true
    now = Date.now()
  }
  function act(name, account, org) {
    if (busy) return
    message = "Working…"
    failed = false
    operation.command = ["python3", helper, "action", name, account || "", org || ""]
    operation.running = true
  }
  function resetText(value) {
    if (value === null || value === undefined || value === "") return ""
    var time = typeof value === "number" ? (value < 1e12 ? value * 1000 : value) : Date.parse(value)
    if (!isFinite(time)) return ""
    var minutes = Math.max(0, Math.ceil((time - now) / 60000))
    if (minutes === 0) return "reset due"
    if (minutes >= 1440) return "resets in " + Math.floor(minutes / 1440) + "d " + Math.floor(minutes % 1440 / 60) + "h"
    return "resets in " + Math.floor(minutes / 60) + "h " + (minutes % 60) + "m"
  }
  function number(value) { return Number(value || 0).toLocaleString(Qt.locale(), 'f', 0) }

  Component.onCompleted: refresh()
  onPollingChanged: if (polling) refresh()
  Timer { interval: root.polling ? 1500 : 15000; running: root.monitoring; repeat: true; onTriggered: root.refresh() }
  Process {
    id: poll
    command: ["python3", root.helper, "snapshot"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var next = JSON.parse(text)
          root.snapshotData = next
          if (!root.pausedLog) root.consoleText = (next.lines || []).join("\n")
        } catch (e) {
          root.snapshotData = {online: false, accounts: [], meters: [], message: "Could not read TeamClaude status."}
        }
      }
    }
  }
  Process {
    id: operation
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var reply = JSON.parse(text)
          root.message = reply.message || "Done."
          root.failed = reply.ok !== true
        } catch (e) { root.message = "The action did not return a result."; root.failed = true }
        root.refresh()
      }
    }
  }

  LabelText {
    text: root.online ? "● Running · " + (root.snapshotData.managed ? "widget service" : "external server") + " · " + root.number(root.snapshotData.requests) + " requests"
                      : "○ TeamClaude is stopped or unavailable"
    font.bold: true
  }
  LabelText { visible: !root.online; text: root.snapshotData.message || "Start your proxy to see account usage." }
  Flow {
    width: parent ? parent.width : 0
    spacing: Style.space(6)
    ActionButton {
      text: root.online ? (root.snapshotData.managed ? "Stop server" : "Terminal dashboard") : "Start server"
      onClicked: root.act(root.online ? (root.snapshotData.managed ? "stop" : "attach") : "start")
    }
    ActionButton { text: "Add account"; onClicked: root.act("login") }
    ActionButton { text: "Launch Claude"; enabled: root.online && !root.busy; onClicked: root.act("run") }
    ActionButton { text: "Refresh quotas"; enabled: root.online && !root.busy; onClicked: root.act("probe") }
  }
  LabelText {
    visible: root.message !== ""
    text: root.message
    color: root.failed ? Color.urgent : root.muted
  }
  UI.PanelSeparator { width: root.width; foreground: root.fg; visible: root.online }
  LabelText { visible: root.online && !(root.snapshotData.accounts || []).length; text: "No accounts yet. Use Add account to sign in." }
  Repeater {
    model: root.online ? (root.snapshotData.accounts || []) : []
    delegate: Rectangle {
      id: accountCard
      required property var modelData
      readonly property string accountKey: modelData.target + "\n" + modelData.org
      readonly property bool expanded: root.expandedAccount === accountKey
      width: root.width
      implicitHeight: accountColumn.implicitHeight + Style.space(12)
      color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.04)
      border.color: modelData.active ? Color.accent : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.16)
      radius: Style.cornerRadius
      Column {
        id: accountColumn
        x: Style.space(6); y: Style.space(6)
        width: (parent ? parent.width : 0) - Style.space(12)
        spacing: Style.space(4)
        Row {
          width: parent.width; spacing: Style.space(6)
          LabelText {
            width: parent.width - detailButton.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            text: (accountCard.modelData.active ? "● " : "") + accountCard.modelData.name
                  + (accountCard.modelData.disabled ? " · disabled" : "")
            font.bold: true; wrapMode: Text.NoWrap; elide: Text.ElideRight
          }
          ActionButton {
            id: detailButton
            text: accountCard.expanded ? "Less ▴" : "Details ▾"
            onClicked: root.expandedAccount = accountCard.expanded ? "" : accountCard.accountKey
          }
        }
        Row {
          width: parent.width; spacing: Style.space(12)
          Repeater {
            model: accountCard.modelData.meters.slice(0, 2)
            delegate: Meter {
              required property var modelData
              width: (accountColumn.width - Style.space(12)) / 2
              entry: modelData
            }
          }
        }
        Column {
          width: parent.width; spacing: Style.space(6)
          visible: accountCard.expanded
          LabelText {
            text: accountCard.modelData.name + " · " + accountCard.modelData.tier + " · "
                  + (accountCard.modelData.disabled ? "disabled" : accountCard.modelData.status)
            color: root.muted; font.pixelSize: Style.font.caption
          }
          Grid {
            width: parent.width; columns: 2; columnSpacing: Style.space(12); rowSpacing: Style.space(6)
            Repeater {
              model: accountCard.modelData.meters.slice(2)
              delegate: Meter {
                required property var modelData
                width: (accountColumn.width - Style.space(12)) / 2
                entry: modelData
              }
            }
          }
          LabelText {
            text: root.number(accountCard.modelData.usage.totalRequests) + " calls · "
                  + root.number(accountCard.modelData.usage.totalInputTokens) + " input · "
                  + root.number(accountCard.modelData.usage.totalOutputTokens) + " output\n"
                  + root.number(accountCard.modelData.usage.totalCacheReadTokens) + " cache read · "
                  + root.number(accountCard.modelData.usage.totalCacheCreationTokens) + " cache written"
            font.pixelSize: Style.font.caption; color: root.muted
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            ActionButton { text: "Prefer"; enabled: !root.busy && !accountCard.modelData.disabled; onClicked: root.act("switch", accountCard.modelData.target, accountCard.modelData.org) }
            ActionButton { text: accountCard.modelData.disabled ? "Enable" : "Disable"; onClicked: root.act(accountCard.modelData.disabled ? "enable" : "disable", accountCard.modelData.target, accountCard.modelData.org) }
            ActionButton { text: "Remove…"; onClicked: { root.pendingRemove = accountCard.modelData.target; root.pendingOrg = accountCard.modelData.org } }
          }
        }
      }
    }
  }
  Column {
    width: parent ? parent.width : 0; spacing: Style.space(8); visible: root.pendingRemove !== ""
    LabelText { text: "Remove " + root.pendingRemove + " and its saved credentials?"; color: Color.urgent }
    Row {
      spacing: Style.space(8)
      ActionButton { text: "Remove account"; onClicked: { root.act("remove", root.pendingRemove, root.pendingOrg); root.pendingRemove = "" } }
      ActionButton { text: "Cancel"; onClicked: root.pendingRemove = "" }
    }
  }
  UI.PanelSeparator { width: parent ? parent.width : 0; foreground: root.fg }
  Row {
    spacing: Style.space(8)
    LabelText { width: implicitWidth; text: "ACTIVITY"; anchors.verticalCenter: parent.verticalCenter; font.bold: true }
    ActionButton { text: root.pausedLog ? "Resume" : "Pause"; onClicked: root.pausedLog = !root.pausedLog }
    ActionButton { text: root.followLog ? "Following" : "Follow"; selected: root.followLog; onClicked: root.followLog = !root.followLog }
    ActionButton { text: "Help"; selected: root.showHelp; onClicked: root.showHelp = !root.showHelp }
  }
  LabelText {
    visible: root.online && root.snapshotData.logAvailable === false && root.snapshotData.logMessage
    text: root.snapshotData.logMessage
    color: root.muted; font.pixelSize: Style.font.caption
  }
  LabelText {
    visible: root.showHelp && root.snapshotData.logAvailable
    text: "Recent activity · " + (root.snapshotData.logUpdated ? "last written " + new Date(root.snapshotData.logUpdated * 1000).toLocaleTimeString() : "no log yet")
    color: root.muted; font.pixelSize: Style.font.caption
  }
  Rectangle {
    width: parent ? parent.width : 0; height: Style.space(130)
    color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.05)
    border.color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.15)
    radius: Style.cornerRadius
    Flickable {
      id: consoleFlick
      anchors.fill: parent; anchors.margins: Style.space(8)
      clip: true; contentWidth: width; contentHeight: consoleOutput.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
      TextEdit {
        id: consoleOutput
        width: consoleFlick.width
        readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WrapAnywhere
        color: root.fg; font.family: "monospace"; font.pixelSize: Style.font.caption
        text: root.consoleText || (root.online
          ? (Number(root.snapshotData.requests || 0) === 0
              ? "No Claude requests have passed through this TeamClaude server yet.\nUse Launch Claude here (or `teamclaude run`) to send requests through it.\n\nCompleted requests appear here. The terminal TUI also shows in-progress calls."
              : "No completed request lines are in the activity log yet.")
          : "Waiting for TeamClaude request activity…")
        onTextChanged: if (root.followLog) Qt.callLater(function() { consoleFlick.contentY = Math.max(0, consoleFlick.contentHeight - consoleFlick.height) })
      }
    }
  }
  LabelText {
    visible: root.showHelp
    text: "Each row appears after a request completes, like the terminal's recent activity list. In-progress requests stay visible in the terminal.\nThe Start button enables logging. For a terminal server, use:\nteamclaude server --activity-log " + (root.snapshotData.logPath || "~/.local/state/omarchy/teamclaude/activity.log")
    color: root.muted; font.pixelSize: Style.font.caption
  }

  component LabelText: Text {
    width: parent ? parent.width : 0
    textFormat: Text.PlainText; wrapMode: Text.Wrap
    color: root.fg; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
  }
  component ActionButton: UI.Button {
    bordered: true; focusable: true; enabled: !root.busy
    horizontalPadding: Style.space(7); verticalPadding: Style.space(3)
    foreground: root.fg; fontSize: Style.font.caption
    opacity: enabled ? 1 : 0.45
  }
  component Meter: Column {
    property var entry
    width: parent ? parent.width : 0; spacing: Style.space(2)
    LabelText {
      text: String(entry.label).replace("Session · 5 hours", "5h") + " · " + (entry.percent === null ? "unknown" : Math.round(entry.percent * 100) + "%")
            + (root.resetText(entry.reset) ? " · " + root.resetText(entry.reset).replace("resets in ", "↻ ") : "")
      font.pixelSize: Style.font.caption
    }
    Rectangle {
      width: parent ? parent.width : 0; height: Style.space(4); radius: height / 2
      color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.12)
      Rectangle {
        width: (parent ? parent.width : 0) * Math.max(0, Math.min(1, entry.percent || 0))
        height: parent.height; radius: height / 2
        color: entry.percent >= 0.9 ? Color.urgent : Color.accent
      }
    }
  }
}

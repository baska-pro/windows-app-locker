# Telegram Control

## Setup

Create a bot with BotFather, obtain its bot token, and obtain the Telegram Chat ID that will be the single authorized owner. Enter both values in the first-run wizard.

The token is encrypted with Windows DPAPI and is intended to be decryptable only by the same Windows user profile.

## Main menu

Send:

```text
/menu
```

The bot returns inline buttons for status, app list, lock all, temporary unlock all, pause, resume, and help.

## Commands

```text
/status
/apps
/lock <app>
/unlock <app> [minutes]
/lockall
/unlockall [minutes]
/launch <app> [minutes]
/pause [minutes]
/resume
/logs [count]
/ping
/help
```

Examples:

```text
/unlock chrome 10
/lock telegram
/launch chrome 5
/logs 30
```

## Authorization

Every Telegram update is checked against the configured owner Chat ID. Requests from other chats are rejected and recorded in the local log.

## Remote-control boundary

Telegram can only control applications already registered in the local App Locker configuration. `/launch` does not accept arbitrary executables or shell commands.

## Changing Telegram settings

Open the dashboard, choose **Telegram**, verify the local PIN, then update the owner Chat ID, enabled state, or bot token. Restart the app after changing Telegram connection settings.

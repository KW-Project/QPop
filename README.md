# QPop

Get a notification on your phone the moment your queue pops, so you can walk away from your PC
while you wait. Works with **League of Legends**, **TFT** and **Deadlock**, on **iPhone** and **Android**.

## Install (2 minutes)

1. Run **`QPop-Setup-<version>.exe`**. Windows may say **"Windows protected your PC"** because the app
   isn't signed: click **More info → Run anyway**. No admin password is needed.
2. Click through the installer (keep **Start QPop when Windows starts** ticked) and finish with
   **Open QPop now** ticked.
3. The QPop window opens:
   - **Connect your phone:** pick iPhone or Android, scan the left QR code to install the free
     **ntfy** app, then subscribe to your topic:
     - *iPhone:* in ntfy tap **+** and enter the topic shown (scan the right QR code to copy it).
     - *Android:* scan the right QR code and ntfy subscribes automatically.
   - Press **Send test notification**. If your phone buzzes, you're done.
   - **Deadlock players:** if the Deadlock box says the launch option is missing, click **Add it for me**
     (Steam closes and reopens for a moment).
4. Close the window. QPop keeps running as a **bell icon in your system tray** (by the clock;
   check the **^** arrow if you don't see it) and starts automatically with Windows. To open it
   again, click the bell or search **QPop** in the Start menu.

## Using it

Just queue up. When the match is found, your phone buzzes.

The tray bell is **blue** while watching, **orange** for a minute after a match pops, and **grey** when paused.
**Left-click** it to open the window. **Right-click** it to pause, send a test, link a new phone, or quit.

**New phone?** Right-click the bell → **Link a new phone...** You can keep both phones, or replace the old
one so it stops getting alerts.

## Tips

- **iPhone:** Settings → Notifications → ntfy → turn on **Time Sensitive Notifications** so alerts get
  through Focus / Do Not Disturb.
- **Android:** Settings → Apps → ntfy → Battery → **Unrestricted**, so alerts aren't delayed.
- **Deadlock** alerts arrive when your match starts loading. **League/TFT** alerts arrive on the Accept screen.

## Updating

When a new version is out, QPop tells you (a Windows notification, plus **Update available** in the
tray menu and the window). Download the new installer and run it. Your settings and phone link are kept.

## Uninstall

**Settings → Apps → Installed apps → QPop → Uninstall.** It asks whether to delete your settings too:
say **No** if you might reinstall, so your phone stays linked.

## Privacy

QPop only reads your game clients' local status. Nothing is collected. Alerts are sent through
[ntfy.sh](https://ntfy.sh) to a random private topic made just for you. Anyone who knows that topic name
could read or send alerts, so don't share it.

---
Developers: see [DEVELOPING.md](DEVELOPING.md).

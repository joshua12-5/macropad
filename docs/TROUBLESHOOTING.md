# Troubleshooting

Start with the quick checks, then find your symptom below. Setup steps are in the
[user guide](USER_GUIDE.md).

**Quick checks**

- Use a **data** USB cable (many USB-C cables only charge) and try another port, ideally one
  directly on the computer rather than a hub.
- Make sure the board is not sitting in the bootloader. If a drive called `RPI-RP2` is showing,
  the macropad firmware is not running.
- Check the versions: `MacropadConfigurator --version`, and in the app **Device → Connect / Get
  device info**. Firmware `0.N` goes with configurator `0.N.x`.
- Check the installation: `MacropadConfigurator --self-test` should end with
  `SELF-TEST OK: 8/8 checks passed`.
- List what the hardware test tool can see: `MacropadConfigurator --hil --list`. A working
  macropad shows VID `0x2e8a`, PID `0xc001` and a **CONFIG** interface (usage page `0xff00`).
- **Debug UART** (optional): connect a 3.3 V USB-serial adapter to GP0 (TX) and GND at
  **115200 baud**. At boot the firmware prints `=== Macropad firmware 0.25 ===`, the profile
  slots, and either `OLED OK at I2C 0x3C` or `OLED NOT FOUND`. After that it logs every key,
  profile, macro and upload event.

---

## Device not detected

**The keys type nothing and the configurator finds no macropad.**

The firmware is probably not running. Check the cable and see
[The UF2 doesn't boot](#the-uf2-doesnt-boot).

**The keys work, but Device → Connect says `No macropad config HID found (VID=0x2e8a
PID=0xc001 usage_page=0xff00)`.**

The keyboard interface works but the app cannot open the configuration interface.

- **Windows:** in Device Manager → *Human Interface Devices*, look for the entries with
  `VID_2E8A&PID_C001`. There should be several: keyboard, consumer control and a vendor-defined
  device. No driver is needed; if one shows an error, uninstall that device and replug. Some
  endpoint-security tools block access to vendor HID devices, so try another machine to rule
  that out.
- **macOS:** check **System Information → USB** for *RP2040 Macropad*. The app opens only the
  vendor configuration interface, which normally needs no permission. If macOS asks for **Input
  Monitoring**, allow it and restart the app.
- **Linux:** `lsusb | grep -i 2e8a:c001` should list the device. If it does and Connect still
  fails, it is almost always the permission problem below. Check `dmesg` for USB errors.
- **Running from source:** make sure a hidapi binding is installed (`pip install -r
  requirements.txt` installs `hidapi`). Otherwise the app reports `Python module 'hid' (hidapi)
  is not available`.

**`timeout waiting for device response`**

The device was found but did not answer within 500 ms. Replug it and try again. If it keeps
happening, run the HIL `ping` test (see [Reporting a bug](#reporting-a-bug)) and include the
output in your report.

## Permission errors on Linux

Symptom: Connect fails with `cannot open HID path … Permission denied` (or similar), while the
keys work normally.

1. Install the udev rule shipped in the Linux tarball (`./install.sh`), or copy
   [`packaging/linux/70-macropad.rules`](../packaging/linux/70-macropad.rules) by hand:

   ```bash
   sudo install -m 0644 70-macropad.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

2. **Unplug and replug** the macropad.
3. Check it: `ls -l /dev/hidraw*` then `getfacl /dev/hidrawN` for the macropad's node. Your
   user should be listed. The rule uses `TAG+="uaccess"`, which grants access to the user logged
   in at the local seat.
4. Over SSH, in a container, or on a system without systemd-logind, `uaccess` does not apply.
   Use a group instead: change the rule to `MODE="0660", GROUP="plugdev"` (or another group you
   are in), reload, and replug. Avoid `MODE="0666"` on shared machines.

Running the app with `sudo` also works, but it is not recommended: the app then keeps its data
in root's home folder.

## The UF2 doesn't boot

- **No `RPI-RP2` drive appears.** Hold **BOOT** *while* plugging in (or hold BOOT, tap RESET,
  release BOOT). Try another cable or port.
- **The copy finishes but `RPI-RP2` comes back straight away,** or nothing happens:
  - Check the file: `sha256sum -c macropad-fw-X.Y.Z.uf2.sha256` (see
    [Flash the firmware](USER_GUIDE.md#flash-the-firmware)). A browser that saved an HTML error
    page instead of the file is a common cause.
  - Make sure it is the macropad UF2 from this project. The firmware is built for the RP2040
    (Waveshare RP2040-Zero), not the RP2350.
- **The drive disappears but no keyboard shows up and the OLED stays dark.**
  - Connect the debug UART (see the quick checks). If the banner prints, the firmware is running
    and the problem is USB (cable, hub, port) or the OLED (next section).
  - If nothing prints, reflash. If you build it yourself, use `-DPICO_BOARD=waveshare_rp2040_zero`
    and Pico SDK 2.1.1 as in [firmware/README.md](../firmware/README.md).
- **It worked before an update.** Reflash the previous release's UF2. Your settings are not
  touched by flashing.

## Blank OLED

1. **The display may be off on purpose.** With the default idle settings, the screen switches
   off after 600 s without input. Press a key or turn the knob; the waking input is not sent to
   the computer. You can change or disable the timer (0 = never) in **Tools → Idle animation… →
   Screen off after**.
2. **Read the UART log.** `OLED NOT FOUND` means neither I2C address answered.
   - Check the wiring: **SDA → GP4**, **SCL → GP5** (swapping them is the most common mistake),
     **VCC → 3V3**, **GND → GND**.
   - The firmware tries address **0x3C**, then **0x3D**. Modules often print the 8-bit forms
     **0x78** (= 0x3C) and **0x7A** (= 0x3D) next to the address jumper; either setting works.
   - Most modules have the I2C pull-ups on board. If yours has none, add about 4.7 kΩ from SDA
     and from SCL to 3V3.
3. `OLED OK at I2C 0x3C` but the picture is garbled, shifted by two pixels, or blank: the
   module may have an **SH1106** controller (common on 1.3″ modules) instead of an SSD1306.
   Only the SSD1306 128 × 64 is supported.
4. The OLED works, but **no animation plays when idle**:
   - **Play animation when idle** may be off, or **Start after** may be 0 (never).
   - With no animation uploaded, the built-in starfield plays.
   - **Preview on device** in the editor tests the display straight away.

## Encoder turns the wrong way, or skips or doubles steps

- **Reversed direction:** swap the **CLK** (GP2) and **DT** (GP3) wires, or, without
  soldering, swap the profile's **CW** and **CCW** actions in the configurator.
- **One action every two clicks, or two actions per click:**
  - The firmware turns every **4 valid quadrature transitions** into one step
    (`DETENTS_PER_CLICK` in `firmware/src/encoder.c`), which suits the usual KY-040 / EC11 with
    one full cycle per detent.
  - Half-step encoders make only 2 transitions per click and so give one step every two clicks.
  - Set the constant to your encoder's transitions per click and rebuild the firmware.
- **Random extra or missed steps:**
  - Power the KY-040 from **3V3**, not 5 V, and keep the encoder wires short.
  - If the contacts are noisy, add 10–100 nF capacitors from CLK and DT to GND.
  - Also check that the steps are not coming from the OS: one `VOLUME` step moves the system
    volume by whatever step size the OS uses.
- **A press opens the profile menu, or does nothing:**
  - Holding the knob for about **0.8 s** opens the profile menu, and in that case the Press
    action does not fire. Release sooner for a normal press.
  - A press that wakes the idle animation is swallowed.

## Ghost key presses

**Pressing three keys that form the corners of a rectangle also triggers the fourth, or keys
trigger their neighbours.**

This is ghosting: the diodes are missing, reversed, or shorted.

- Each switch needs its own diode. The **cathode** (banded end) goes to the **row** wire (GP8 /
  GP9 / GP10) and the anode goes to the switch, whose other leg is on the column wire (GP11–GP14).
  The firmware scans COL2ROW; a diode the wrong way round makes that key dead.
- **A key that is always "pressed"** points to a short between its row and column.
- To test, run `MacropadConfigurator --hil --interactive`, which walks you through every key and
  encoder action, or watch the `KEY n` lines in the UART log.

## Flash write or upload failures

Uploads go over the configuration interface in 48-byte chunks. The device checks a CRC and the
structure before it keeps anything. Error messages look like
`… failed: device NAK EBUSY (code 4)`:

| Message | Meaning | What to do |
|---------|---------|------------|
| `NAK EBUSY` | Another upload is in progress (profile, macro and animation uploads exclude each other), or a flash write failed. | Close other configurator windows or instances, wait a few seconds, try again. Replug if it persists. |
| `NAK EBADMSG` | CRC or structure check failed. The device discarded the upload; a failed animation upload leaves no animation, so the starfield plays. | Retry. If it repeats, try another cable or port and run the HIL suite. |
| `NAK EINVAL` | The device rejected the request as invalid, e.g. a bad slot, an out-of-order chunk, or data too large. | Check the limits: slots 0–4, macros ≤ 24 steps, animations ≤ 128 KiB encoded. |
| `timeout waiting for device response` | No answer within 500 ms. | Replug and retry; see above. |
| `Upload finished but the read-back does not match.` | The animation upload completed but verification failed. | Upload again. |
| Upload items greyed out | Not connected, firmware too old for the feature, or protocol mismatch. | Connect first; see the tooltip; update firmware. |

Notes:

- Every profile or macro upload, **Push idle settings** and **Save device state** rewrites a
  4 KiB flash block. The flash is rated for about 100,000 erase cycles per block. Normal use,
  including auto-switch (whose saves are debounced), is far from that.
- While a block is being written (about 50 ms, datasheet typical), the macropad pauses key
  scanning, so keys pressed at exactly that moment can be missed. See
  [Idle animations](USER_GUIDE.md#idle-animations).
- If an animation upload is interrupted (cable pulled, **Cancel**), the device throws away the
  partial data and plays the built-in starfield until you upload again.

## Protocol or version mismatch

- **`Protocol mismatch: device proto_ver=X, host expects Y`.** The firmware and the
  configurator speak different protocol versions. Uploads, **Save device state** and
  auto-switch stay disabled until both come from compatible releases. Install the firmware and
  the configurator from the **same release** (firmware `0.N` ↔ configurator `0.N.x`).
- **Firmware older than the configurator** (same protocol): the app works, but features the
  firmware lacks are greyed out, with the needed version in the tooltip. For example, idle
  animations need firmware 0.25 and the animation editor explains this instead of sending
  anything. Update the firmware.
- **Firmware newer than the configurator:** update the configurator.

The version rules are in [VERSIONING.md](VERSIONING.md).

## Reporting a bug

Please open an issue at <https://github.com/joshua12-5/macropad/issues> and include:

1. The OS and version, and the output of `MacropadConfigurator --version`.
2. The **Device → Connect / Get device info** text, or a screenshot of it.
3. A self-test report: `MacropadConfigurator --self-test --report selftest.txt`.
4. A **hardware-in-the-loop** report from the real device:

   ```bash
   MacropadConfigurator --hil --json hil-report.json              # safe: no flash writes
   MacropadConfigurator --hil --allow-flash-write --json hil-report.json
   ```

   The second command also tests uploads. It backs up the profile, macro and animation it
   overwrites and restores them afterwards. The final `restore_check` test confirms nothing
   changed, but only use it if you are fine with a few flash writes. Add `--interactive` for a
   guided key and encoder check. From source, the same tool is
   `python configurator/scripts/hil_test.py …`. Exit codes: 0 = no failures, 1 = a test
   failed, 2 = no device found.
5. For firmware problems, the UART log from power-on until the problem appears.

What each HIL test covers: [HARDWARE_TEST.md](HARDWARE_TEST.md).

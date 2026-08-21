'use strict';

import ObjC from 'frida-objc-bridge';

function screenState() {
  const controller = ObjC.classes.SBBacklightController.sharedInstance();
  const lockManager = ObjC.classes.SBLockScreenManager.sharedInstance();
  return {
    screen_on: Boolean(controller.screenIsOn()),
    backlight_state: Number(controller.backlightState()),
    ui_locked: Boolean(lockManager.isUILocked()),
  };
}

rpc.exports = {
  async wake() {
    await ObjC.schedule(ObjC.mainQueue, () => {
      const controller = ObjC.classes.SBBacklightController.sharedInstance();
      controller.turnOnScreenFullyWithBacklightSource_(0);
    });
    return screenState();
  },
  state() {
    return screenState();
  },
};

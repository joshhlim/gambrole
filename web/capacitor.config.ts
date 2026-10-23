import type { CapacitorConfig } from "@capacitor/cli";
import { KeyboardResize } from "@capacitor/keyboard";

const config: CapacitorConfig = {
  appId: "com.joshhlim.gambrole",
  appName: "GamBROle",
  webDir: "out",
  // Behind the page while it loads — the app's light background, so the
  // hand-off from the splash never flashes white.
  backgroundColor: "#f7f5f0",
  plugins: {
    SplashScreen: {
      // Hidden by NativeShell once the first screen has rendered, not on a
      // timer: no blank page between the splash and the app.
      launchAutoHide: false,
    },
    Keyboard: {
      // Shrink the page to the space above the keyboard, so the field
      // you're typing in stays visible.
      resize: KeyboardResize.Native,
    },
  },
};

export default config;

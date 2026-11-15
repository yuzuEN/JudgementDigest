import { MoonIcon, SunIcon } from "lucide-react";
import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { currentlyDark, onThemeChange, setThemePref } from "../../theme";

/** 頁首的淺色／深色切換。按鈕上寫的是「切換之後」的樣子，窄螢幕只留圖示（有 aria-label）。 */
export function ThemeToggle() {
  const dark = useSyncExternalStore(onThemeChange, currentlyDark, () => false);
  const next = dark ? "淺色" : "深色";
  const Icon = dark ? SunIcon : MoonIcon;
  return (
    <Button type="button" variant="ghost" aria-label={`切換成${next}模式`} title={`切換成${next}模式`}
      onClick={() => setThemePref(dark ? "light" : "dark")}
      className="no-print min-h-11 gap-1.5 px-2.5 font-semibold text-link hover:bg-secondary hover:text-link">
      <Icon className="size-5" aria-hidden="true" />
      <span className="max-sm:hidden">{next}</span>
    </Button>
  );
}

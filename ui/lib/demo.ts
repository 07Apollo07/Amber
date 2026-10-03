import { toast } from "sonner"

/** Buttons for features that don't have an API yet call this instead. */
export function demoAction(label: string, description = "Demo only, not connected to the backend yet.") {
  toast(label, { description })
}

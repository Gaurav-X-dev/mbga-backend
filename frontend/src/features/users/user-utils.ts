import type { User } from "../../api/users.api";
import { formatMobileNumber } from "../../utils/mobile";

export function userDisplayName(user: Pick<User, "full_name" | "username" | "email" | "mobile_number">): string {
  return user.full_name || user.username || user.email || formatMobileNumber(user.mobile_number) || "Unnamed user";
}

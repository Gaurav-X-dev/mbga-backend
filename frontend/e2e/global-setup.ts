import { cleanupE2EData } from "./test-data";

export default function globalSetup() {
  cleanupE2EData("setup");
}

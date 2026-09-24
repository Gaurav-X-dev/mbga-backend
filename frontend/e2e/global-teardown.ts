import { cleanupE2EData } from "./test-data";

export default function globalTeardown() {
  cleanupE2EData("teardown");
}

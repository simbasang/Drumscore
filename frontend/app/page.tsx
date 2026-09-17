import { getBackendHealth } from "@/lib/api/health";
import styles from "./page.module.css";

async function fetchBackendStatus(): Promise<string> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  try {
    const health = await getBackendHealth(baseUrl);
    return health.status;
  } catch {
    return "unreachable";
  }
}

export default async function Home() {
  const backendStatus = await fetchBackendStatus();

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>Drumscore</h1>
        <p>Backend status: {backendStatus}</p>
      </main>
    </div>
  );
}

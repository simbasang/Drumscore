import JobForm from "@/components/JobForm";
import styles from "./page.module.css";

export default function Home() {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>Drumscore</h1>
        <p>Generate playable drum notation from a song.</p>
        <JobForm apiBaseUrl={apiBaseUrl} />
      </main>
    </div>
  );
}

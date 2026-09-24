import { connection } from "next/server";

import NewProjectForm from "@/components/NewProjectForm";
import ProjectLibrary from "@/components/ProjectLibrary";
import { getApiBaseUrl } from "@/lib/api/apiBaseUrl";
import styles from "./page.module.css";

export default async function Home() {
  // Render per request: otherwise this page is prerendered at build time and
  // the API URL is frozen into the image.
  await connection();
  const apiBaseUrl = getApiBaseUrl();

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>Drumscore</h1>
        <p>Generate playable drum notation from a song.</p>
        <NewProjectForm apiBaseUrl={apiBaseUrl} />
        <ProjectLibrary apiBaseUrl={apiBaseUrl} />
      </main>
    </div>
  );
}

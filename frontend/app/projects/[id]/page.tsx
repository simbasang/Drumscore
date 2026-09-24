import Link from "next/link";

import ProjectView from "@/components/ProjectView";
import { getApiBaseUrl } from "@/lib/api/apiBaseUrl";
import styles from "../../page.module.css";

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const apiBaseUrl = getApiBaseUrl();

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <Link href="/">← All projects</Link>
        <ProjectView apiBaseUrl={apiBaseUrl} projectId={id} />
      </main>
    </div>
  );
}

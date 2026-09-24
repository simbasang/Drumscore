import Link from "next/link";

import ProjectView from "@/components/ProjectView";
import styles from "../../page.module.css";

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <Link href="/">← All projects</Link>
        <ProjectView apiBaseUrl={apiBaseUrl} projectId={id} />
      </main>
    </div>
  );
}

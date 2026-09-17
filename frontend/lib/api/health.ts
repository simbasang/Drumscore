export interface BackendHealth {
  status: string;
}

export async function getBackendHealth(baseUrl: string): Promise<BackendHealth> {
  const response = await fetch(`${baseUrl}/api/health`);

  if (!response.ok) {
    throw new Error("Backend health check failed");
  }

  return response.json();
}

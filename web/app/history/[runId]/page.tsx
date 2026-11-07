import { redirect } from "next/navigation";

export default async function HistoryByIdPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  redirect(`/runs?run=${encodeURIComponent(runId)}`);
}

import Link from "next/link";

export default function NotFound() {
  return <main className="grid min-h-screen place-items-center bg-paper p-6 text-ink">
    <section className="surface max-w-lg p-8 text-center">
      <p className="eyebrow">404 · Not found</p>
      <h1 className="mt-3 text-2xl font-semibold">This page is not in the evidence trail.</h1>
      <p className="mt-2 text-sm leading-6 text-muted">The requested route does not exist in this prototype.</p>
      <Link href="/" className="mt-5 inline-flex rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-white">Return to workspace</Link>
    </section>
  </main>;
}

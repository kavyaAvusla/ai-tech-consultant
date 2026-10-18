export default function HomePage() {
  return (
    <main>
      <h1>Inbox agent</h1>
      <p>
        Part A drafts support replies from the local Knowledge Brain. Run the
        batch from this folder:
      </p>
      <p>
        <code>npm run pipeline -- --n 8</code>
      </p>
      <p>This page does not call the model or the knowledge service.</p>
    </main>
  );
}

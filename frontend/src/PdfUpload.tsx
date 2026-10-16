
import { useState } from "react";

const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export default function PdfUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);

  async function handleUpload() {
    if (!file) {
      setError(true);
      setMessage("Veuillez sélectionner un fichier PDF.");
      return;
    }

    if (file.type !== "application/pdf" &&
        !file.name.toLowerCase().endsWith(".pdf")) {
      setError(true);
      setMessage("Veuillez sélectionner un fichier PDF.");
      return;
    }

    const token = localStorage.getItem("token");

    if (!token) {
      setError(true);
      setMessage("Veuillez vous connecter avant d'importer un PDF.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setLoading(true);
    setError(false);
    setMessage("");

    try {
      const response = await fetch(
        `${API_URL}/documents/upload`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
          },
          body: formData,
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Échec de l'importation du PDF."
        );
      }

      setMessage(
        `${data.message} ${data.chunks_indexed} chunks indexés.`
      );
      setFile(null);
    } catch (err) {
      setError(true);
      setMessage(
        err instanceof Error
          ? err.message
          : "Une erreur est survenue."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-3">
        <div className="rounded-xl bg-indigo-100 p-3 text-indigo-600">
          📄
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">
            Base de connaissances
          </h2>
          <p className="text-sm text-gray-500">
            Importez un document PDF pour interroger son contenu.
          </p>
        </div>
      </div>

      <label
        htmlFor="pdf-file"
        className="block cursor-pointer rounded-xl border-2 border-dashed border-gray-300 p-6 text-center hover:border-indigo-500"
      >
        <span className="text-3xl">⬆️</span>
        <p className="mt-2 font-medium text-gray-800">
          Choisir un fichier PDF
        </p>
        <p className="mt-1 text-sm text-gray-500">
          Sélectionnez un document depuis votre ordinateur.
        </p>
        <input
          id="pdf-file"
          type="file"
          accept=".pdf,application/pdf"
          className="mt-4 block w-full text-sm"
          onChange={(e) =>
            setFile(e.target.files?.[0] ?? null)
          }
        />
      </label>

      {file && (
        <p className="mt-3 text-sm text-gray-600">
          Fichier sélectionné : {file.name}
        </p>
      )}

      <button
        type="button"
        onClick={handleUpload}
        disabled={loading || !file}
        className="mt-4 w-full rounded-xl bg-indigo-600 px-4 py-3 font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? "Importation et indexation..." : "Importer le PDF"}
      </button>

      {message && (
        <p
          role="status"
          className={`mt-4 rounded-lg p-3 text-sm ${
            error
              ? "bg-red-50 text-red-700"
              : "bg-green-50 text-green-700"
          }`}
        >
          {message}
        </p>
      )}
    </section>
  );
}

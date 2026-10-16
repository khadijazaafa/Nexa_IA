
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import {
  Activity,
  ArrowUp,
  BookOpen,
  Bot,
  FileText,
  Globe,
  History,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquare,
  Paperclip,
  Plus,
  Search,
  Sparkles,
  UploadCloud,
  User,
  X,
  Trash2,
} from "lucide-react";
import { apiRequest, login, sendChatMessage } from "./api";
import "./index.css";

const API_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const MAX_FILE_SIZE = 20 * 1024 * 1024;

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type StoredMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

type ConversationItem = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

type DocumentStatus = "Indexed" | "Processing" | "Error";

type DocumentItem = {
  id: string;
  name: string;
  status: DocumentStatus;
  chunksIndexed?: number;
  error?: string;
};

type Tab =
  | "Chat Workspace"
  | "Knowledge Base"
  | "Web Research";

type ApiResponse = {
  access_token?: string;
  response?: unknown;
  answer?: unknown;
  output?: unknown;
  detail?: unknown;
  message?: unknown;
  chunks_indexed?: unknown;
  session_id?: string;
  conversation_id?: number;
  document_id?: string | number;
};

function createId(): string {
  return crypto.randomUUID();
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Une erreur inattendue est survenue.";
}

function isAuthenticationError(message: string): boolean {
  const normalized = message.toLowerCase();

  return (
    normalized.includes("not authenticated") ||
    normalized.includes("invalid token") ||
    normalized.includes("token has expired") ||
    normalized.includes("401") ||
    normalized.includes("session expirée")
  );
}

function getApiError(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const body = data as ApiResponse;

    if (typeof body.detail === "string") {
      return body.detail;
    }

    if (typeof body.message === "string") {
      return body.message;
    }
  }

  return `Échec de la requête (HTTP ${status}).`;
}

async function readApiResponse(
  response: Response
): Promise<unknown> {
  const text = await response.text();

  if (!text.trim()) {
    return {};
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error(
      "Le serveur a renvoyé une réponse JSON invalide."
    );
  }
}

async function authenticatedFetch(
  path: string,
  token: string,
  init: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);

  return fetch(`${API_URL}${path}`, {
    ...init,
    headers,
  });
}

export default function App() {
  // AUTHENTIFICATION

  const [token, setToken] = useState(
    () => localStorage.getItem("token") || ""
  );

  const [authMode, setAuthMode] =
    useState<"login" | "signup">("login");

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");

  // WORKSPACE

  const [activeTab, setActiveTab] =
    useState<Tab>("Chat Workspace");

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);

  const [sessionId, setSessionId] = useState(createId);
  const [activeConversationId, setActiveConversationId] =
    useState<number | null>(null);

  const [chatHistory, setChatHistory] =
    useState<ConversationItem[]>([]);

  const [historyLoading, setHistoryLoading] = useState(false);

  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);

  // GESTION DU TOKEN EXPIRÉ

  function handleUnauthorized(message: string) {
    if (!isAuthenticationError(message)) return;

    localStorage.removeItem("token");
    setToken("");
    setPassword("");
    setAuthError(
      "Votre session a expiré. Veuillez vous reconnecter."
    );
  }

  // CHARGER L'HISTORIQUE DEPUIS FASTAPI

  async function loadConversations(
    currentToken = token
  ): Promise<void> {
    if (!currentToken) return;

    setHistoryLoading(true);

    try {
      const response = await authenticatedFetch(
        "/conversations",
        currentToken
      );

      const data = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(
          getApiError(data, response.status)
        );
      }

      if (!Array.isArray(data)) {
        throw new Error(
          "Le serveur n'a pas retourné une liste de conversations."
        );
      }

      setChatHistory(data as ConversationItem[]);
    } catch (error) {
      const message = getErrorMessage(error);

      console.error(
        "Erreur de chargement des conversations :",
        message
      );

      handleUnauthorized(message);
    } finally {
      setHistoryLoading(false);
    }
  }

  // CHARGER LES DOCUMENTS DEPUIS FASTAPI

  async function loadDocuments(
    currentToken = token
  ): Promise<void> {
    if (!currentToken) return;

    setDocumentsLoading(true);

    try {
      const response = await authenticatedFetch(
        "/documents",
        currentToken
      );

      const data = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(
          getApiError(data, response.status)
        );
      }

      if (!Array.isArray(data)) {
        throw new Error(
          "Le serveur n'a pas retourné une liste de documents."
        );
      }

      const rows = data as Array<{
        id?: string | number;
        document_id?: string | number;
        filename?: string;
        name?: string;
        status?: string;
        chunks_indexed?: number;
        chunksIndexed?: number;
      }>;

      setDocuments(
        rows.map((doc) => {
          const status = (doc.status || "").toLowerCase();

          let normalizedStatus: DocumentStatus = "Processing";

          if (
            status === "indexed" ||
            status === "success"
          ) {
            normalizedStatus = "Indexed";
          } else if (
            status === "error" ||
            status === "failed"
          ) {
            normalizedStatus = "Error";
          }

          return {
            id: String(
              doc.id ??
                doc.document_id ??
                doc.filename ??
                createId()
            ),
            name: doc.filename ?? doc.name ?? "Document PDF",
            status: normalizedStatus,
            chunksIndexed:
              doc.chunks_indexed ?? doc.chunksIndexed,
          };
        })
      );
    } catch (error) {
      const message = getErrorMessage(error);

      console.error(
        "Erreur de chargement des documents :",
        message
      );

      handleUnauthorized(message);
    } finally {
      setDocumentsLoading(false);
    }
  }

  // CHARGEMENT AUTOMATIQUE APRÈS CONNEXION

  useEffect(() => {
    if (!token) {
      setChatHistory([]);
      setDocuments([]);
      return;
    }

    void loadConversations(token);
    void loadDocuments(token);

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // CONNEXION / INSCRIPTION

  async function handleAuth(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    setAuthError("");
    setAuthLoading(true);

    try {
      if (authMode === "signup") {
        await apiRequest("/signup", {
          method: "POST",
          body: JSON.stringify({
            username: username.trim(),
            email: email.trim(),
            password,
          }),
        });

        setAuthMode("login");
        setPassword("");
        setAuthError(
          "Compte créé. Connectez-vous avec vos identifiants."
        );

        return;
      }

      const data = await login(username.trim(), password);

      if (!data.access_token) {
        throw new Error(
          "Le serveur n'a pas retourné de token."
        );
      }

      localStorage.setItem("token", data.access_token);
      setToken(data.access_token);
      setPassword("");
      setAuthError("");
    } catch (error) {
      setAuthError(getErrorMessage(error));
    } finally {
      setAuthLoading(false);
    }
  }

  // DÉCONNEXION

  function logout() {
    localStorage.removeItem("token");

    setToken("");
    setPassword("");
    setMessages([]);
    setQuestion("");
    setAuthError("");
    setAuthMode("login");
    setDocuments([]);
    setChatHistory([]);
    setSessionId(createId());
    setActiveConversationId(null);
    setActiveTab("Chat Workspace");
  }

  // NOUVELLE CONVERSATION

  function newChat() {
    setMessages([]);
    setQuestion("");
    setSessionId(createId());
    setActiveConversationId(null);
    setActiveTab("Chat Workspace");
  }

  // OUVRIR UNE CONVERSATION EXISTANTE

  async function openConversation(
    conversation: ConversationItem
  ) {
    if (!token) return;

    setHistoryLoading(true);

    try {
      const response = await authenticatedFetch(
        `/conversations/${conversation.id}/messages`,
        token
      );

      const data = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(
          getApiError(data, response.status)
        );
      }

      if (!Array.isArray(data)) {
        throw new Error(
          "Le serveur n'a pas retourné la liste des messages."
        );
      }

      const storedMessages = data as StoredMessage[];

      setMessages(
        storedMessages.map((message) => ({
          id: String(message.id),
          role: message.role,
          content: message.content,
        }))
      );

      setActiveConversationId(conversation.id);
      setSessionId(String(conversation.id));
      setQuestion("");
      setActiveTab("Chat Workspace");
    } catch (error) {
      const message = getErrorMessage(error);

      handleUnauthorized(message);
      window.alert(message);
    } finally {
      setHistoryLoading(false);
    }
  }

  // SUPPRIMER UNE CONVERSATION

  async function deleteConversation(
    conversation: ConversationItem
  ) {
    if (!token) return;

    const confirmed = window.confirm(
      `Supprimer la conversation « ${conversation.title} » ?`
    );

    if (!confirmed) return;

    try {
      const response = await authenticatedFetch(
        `/conversations/${conversation.id}`,
        token,
        { method: "DELETE" }
      );

      const data = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(
          getApiError(data, response.status)
        );
      }

      setChatHistory((previous) =>
        previous.filter(
          (item) => item.id !== conversation.id
        )
      );

      if (activeConversationId === conversation.id) {
        newChat();
      }
    } catch (error) {
      const message = getErrorMessage(error);

      handleUnauthorized(message);
      window.alert(message);
    }
  }

  // ENVOYER UN MESSAGE

  async function sendMessage() {
    const text = question.trim();

    if (!text || loading) return;

    if (!token) {
      setAuthError("Veuillez vous connecter.");
      return;
    }

    const userMessage: Message = {
      id: createId(),
      role: "user",
      content: text,
    };

    setMessages((previous) => [
      ...previous,
      userMessage,
    ]);

    setQuestion("");
    setLoading(true);

    try {
      const rawData = await sendChatMessage(
        text,
        sessionId,
        token
      );

      const data = rawData as ApiResponse;

      if (data.session_id) {
        setSessionId(String(data.session_id));
      }

      if (data.conversation_id != null) {
        setActiveConversationId(data.conversation_id);
        setSessionId(String(data.conversation_id));
      }

      const answer =
        data.response ??
        data.answer ??
        data.output ??
        "Aucune réponse reçue du serveur.";

      const assistantMessage: Message = {
        id: createId(),
        role: "assistant",
        content:
          typeof answer === "string"
            ? answer
            : JSON.stringify(answer, null, 2),
      };

      setMessages((previous) => [
        ...previous,
        assistantMessage,
      ]);

      await loadConversations(token);
    } catch (error) {
      const message = getErrorMessage(error);

      handleUnauthorized(message);

      setMessages((previous) => [
        ...previous,
        {
          id: createId(),
          role: "assistant",
          content: `Une erreur est survenue : ${message}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  // RACCOURCI CLAVIER

  function handleComposerKeyDown(
    event: KeyboardEvent<HTMLTextAreaElement>
  ) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  // IMPORTER DES PDF

  async function handleFileSelect(
    files: FileList | File[] | null
  ) {
    if (!files || files.length === 0) return;

    const selectedFiles = Array.from(files);

    const pdfs = selectedFiles.filter(
      (file) =>
        file.name.toLowerCase().endsWith(".pdf") &&
        (file.type === "application/pdf" ||
          file.type === "")
    );

    if (pdfs.length === 0) {
      window.alert(
        "Veuillez sélectionner un fichier PDF valide."
      );
      return;
    }

    if (pdfs.length !== selectedFiles.length) {
      window.alert(
        "Certains fichiers ne sont pas des PDF valides et seront ignorés."
      );
    }

    if (!token) {
      setAuthError(
        "Veuillez vous connecter avant d'importer un PDF."
      );
      return;
    }

    const pendingDocuments: DocumentItem[] = pdfs.map(
      (file) => ({
        id: createId(),
        name: file.name,
        status: "Processing",
      })
    );

    setDocuments((previous) => [
      ...previous,
      ...pendingDocuments,
    ]);

    for (let index = 0; index < pdfs.length; index++) {
      const file = pdfs[index];
      const pendingDocument = pendingDocuments[index];

      try {
        if (file.size === 0) {
          throw new Error("Le fichier PDF est vide.");
        }

        if (file.size > MAX_FILE_SIZE) {
          throw new Error(
            "Le fichier dépasse la limite de 20 Mo."
          );
        }

        const formData = new FormData();
        formData.append("file", file);

        const response = await authenticatedFetch(
          "/documents/upload",
          token,
          {
            method: "POST",
            body: formData,
          }
        );

        const data = await readApiResponse(response);

        if (!response.ok) {
          throw new Error(
            getApiError(data, response.status)
          );
        }

        const uploadData = data as ApiResponse;

        setDocuments((previous) =>
          previous.map((document) =>
            document.id === pendingDocument.id
              ? {
                  ...document,
                  status: "Indexed",
                  chunksIndexed:
                    typeof uploadData.chunks_indexed ===
                    "number"
                      ? uploadData.chunks_indexed
                      : undefined,
                  error: undefined,
                }
              : document
          )
        );

        // Récupérer la liste réelle depuis la base de données.
        await loadDocuments(token);
      } catch (error) {
        const message = getErrorMessage(error);

        handleUnauthorized(message);

        setDocuments((previous) =>
          previous.map((document) =>
            document.id === pendingDocument.id
              ? {
                  ...document,
                  status: "Error",
                  error: message,
                }
              : document
          )
        );
      }
    }
  }

  // ÉCRAN DE CONNEXION

  if (!token) {
    return (
      <div className="auth-page">
        <form className="auth-card" onSubmit={handleAuth}>
          <div className="brand-icon auth-brand-icon">
            <Sparkles size={25} />
          </div>

          <h1>
            {authMode === "login"
              ? "Welcome to Nexa AI"
              : "Create your account"}
          </h1>

          <p>
            {authMode === "login"
              ? "Connectez-vous à votre espace intelligent."
              : "Créez votre compte pour commencer à utiliser Nexa AI."}
          </p>

          <label htmlFor="username">Username</label>
          <input
            id="username"
            value={username}
            onChange={(event) =>
              setUsername(event.target.value)
            }
            placeholder="Votre nom d'utilisateur"
            autoComplete="username"
            required
          />

          {authMode === "signup" && (
            <>
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(event) =>
                  setEmail(event.target.value)
                }
                placeholder="vous@exemple.com"
                autoComplete="email"
                required
              />
            </>
          )}

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) =>
              setPassword(event.target.value)
            }
            placeholder="Votre mot de passe"
            autoComplete={
              authMode === "login"
                ? "current-password"
                : "new-password"
            }
            required
          />

          {authError && (
            <p className="auth-error" role="alert">
              {authError}
            </p>
          )}

          <button
            type="submit"
            className="primary-button auth-submit"
            disabled={authLoading}
          >
            {authLoading && (
              <LoaderCircle size={17} className="spin" />
            )}

            {authLoading
              ? "Veuillez patienter..."
              : authMode === "login"
                ? "Se connecter"
                : "Créer mon compte"}
          </button>

          <p className="auth-switch">
            {authMode === "login"
              ? "Vous n'avez pas de compte ?"
              : "Vous avez déjà un compte ?"}{" "}
            <button
              type="button"
              onClick={() => {
                setAuthMode((previous) =>
                  previous === "login" ? "signup" : "login"
                );
                setAuthError("");
              }}
            >
              {authMode === "login"
                ? "Créer un compte"
                : "Se connecter"}
            </button>
          </p>
        </form>
      </div>
    );
  }

  // APPLICATION PRINCIPALE

  return (
    <div className="app-shell">
      {sidebarOpen && (
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-icon">
              <Sparkles size={23} />
            </div>

            <div>
              <div className="brand-name">Nexa AI</div>
              <div className="brand-subtitle">
                Intelligent workspace
              </div>
            </div>

            <button
              type="button"
              className="icon-button sidebar-close"
              onClick={() => setSidebarOpen(false)}
              aria-label="Fermer le menu"
            >
              <X size={18} />
            </button>
          </div>

          <button
            type="button"
            className="new-chat-button"
            onClick={newChat}
          >
            <Plus size={19} />
            <span>New Chat</span>
            <span className="shortcut">⌘ K</span>
          </button>

          <div className="sidebar-label">WORKSPACE</div>

          <nav className="nav-list">
            <button
              type="button"
              className={`nav-item ${
                activeTab === "Chat Workspace" ? "active" : ""
              }`}
              onClick={() => setActiveTab("Chat Workspace")}
            >
              <MessageSquare size={18} />
              <span>Chat Workspace</span>
            </button>

            <button
              type="button"
              className={`nav-item ${
                activeTab === "Knowledge Base" ? "active" : ""
              }`}
              onClick={() => setActiveTab("Knowledge Base")}
            >
              <BookOpen size={18} />
              <span>Knowledge Base</span>
              <span className="nav-count">
                {documents.length}
              </span>
            </button>

            <button
              type="button"
              className={`nav-item ${
                activeTab === "Web Research" ? "active" : ""
              }`}
              onClick={() => setActiveTab("Web Research")}
            >
              <Globe size={18} />
              <span>Web Research</span>
            </button>
          </nav>

          <div className="sidebar-label history-heading">
            <span>RECENT CHATS</span>
            <History size={15} />
          </div>

          <div className="history-list">
            {historyLoading && chatHistory.length === 0 ? (
              <div className="history-empty">
                Chargement de l'historique...
              </div>
            ) : chatHistory.length === 0 ? (
              <div className="history-empty">
                Aucune conversation enregistrée
              </div>
            ) : (
              chatHistory.map((conversation) => (
                <div
                  className={`history-entry ${
                    activeConversationId === conversation.id
                      ? "active"
                      : ""
                  }`}
                  key={conversation.id}
                >
                  <button
                    type="button"
                    className="history-item"
                    onClick={() =>
                      void openConversation(conversation)
                    }
                    title={conversation.title}
                  >
                    <MessageSquare size={15} />
                    <span>
                      {conversation.title ||
                        "Nouvelle conversation"}
                    </span>
                  </button>

                  <button
                    type="button"
                    className="icon-button history-delete"
                    title="Supprimer la conversation"
                    aria-label="Supprimer la conversation"
                    onClick={() =>
                      void deleteConversation(conversation)
                    }
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
            )}
          </div>

          <div className="sidebar-bottom">
            <div className="system-status">
              <span className="status-dot" />
              <span>Workspace ready</span>
              <Activity size={15} />
            </div>

            <div className="profile-card">
              <div className="avatar">
                {username.trim().charAt(0).toUpperCase() ||
                  "U"}
              </div>

              <div className="profile-text">
                <strong>{username || "My Workspace"}</strong>
                <span>Personal account</span>
              </div>

              <button
                type="button"
                className="icon-button"
                onClick={logout}
                title="Se déconnecter"
                aria-label="Se déconnecter"
              >
                <LogOut size={17} />
              </button>
            </div>
          </div>
        </aside>
      )}

      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            {!sidebarOpen && (
              <button
                type="button"
                className="icon-button"
                onClick={() => setSidebarOpen(true)}
                aria-label="Ouvrir le menu"
              >
                <Menu size={20} />
              </button>
            )}

            <div className="breadcrumb">
              <span>Workspace</span>
              <span className="breadcrumb-separator">/</span>
              <strong>{activeTab}</strong>
            </div>
          </div>

          <div className="topbar-right">
            <span className="model-status">
              <span className="status-dot" />
              AI connected
            </span>

            <div className="model-button">
              <Sparkles size={15} />
              GPT-OSS
            </div>

            <div className="avatar top-avatar">
              {username.trim().charAt(0).toUpperCase() ||
                "U"}
            </div>
          </div>
        </header>

        <div className="page-content">
          {/* CHAT WORKSPACE */}

          {activeTab === "Chat Workspace" && (
            <section className="chat-page">
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    <Sparkles size={14} />
                    YOUR AI ASSISTANT
                  </div>

                  <h1>Chat Workspace</h1>

                  <p>
                    Ask questions, explore your documents and
                    discover insights with AI.
                  </p>
                </div>

                <button
                  type="button"
                  className="outline-button"
                  onClick={newChat}
                >
                  <Plus size={17} />
                  New conversation
                </button>
              </div>

              <div className="chat-card">
                {messages.length === 0 ? (
                  <div className="welcome-area">
                    <div className="welcome-icon">
                      <Bot size={30} />
                    </div>

                    <h2>What can I help you with?</h2>

                    <p>
                      Start a conversation or choose a
                      suggestion below.
                    </p>

                    <div className="suggestion-grid">
                      <button
                        type="button"
                        className="suggestion-card"
                        onClick={() =>
                          setQuestion(
                            "Summarize my uploaded PDF document"
                          )
                        }
                      >
                        <div className="suggestion-icon purple">
                          <FileText size={19} />
                        </div>
                        <strong>Summarize a document</strong>
                        <span>
                          Extract the key ideas from a PDF.
                        </span>
                      </button>

                      <button
                        type="button"
                        className="suggestion-card"
                        onClick={() =>
                          setQuestion(
                            "Explain the concept of attention in AI"
                          )
                        }
                      >
                        <div className="suggestion-icon blue">
                          <Sparkles size={19} />
                        </div>
                        <strong>Learn something new</strong>
                        <span>
                          Understand complex AI concepts.
                        </span>
                      </button>

                      <button
                        type="button"
                        className="suggestion-card"
                        onClick={() =>
                          setQuestion(
                            "Search the web for recent AI research"
                          )
                        }
                      >
                        <div className="suggestion-icon green">
                          <Globe size={19} />
                        </div>
                        <strong>Explore the web</strong>
                        <span>
                          Find information and research sources.
                        </span>
                      </button>

                      <button
                        type="button"
                        className="suggestion-card"
                        onClick={() =>
                          setQuestion(
                            "Compare information from my documents and the web"
                          )
                        }
                      >
                        <div className="suggestion-icon orange">
                          <Search size={19} />
                        </div>
                        <strong>Compare information</strong>
                        <span>
                          Explore different sources and ideas.
                        </span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="messages-area">
                    {messages.map((message) => (
                      <div
                        className={`message-row ${message.role}`}
                        key={message.id}
                      >
                        <div className="message-avatar">
                          {message.role === "assistant" ? (
                            <Sparkles size={17} />
                          ) : (
                            <User size={17} />
                          )}
                        </div>

                        <div className="message-body">
                          <div className="message-author">
                            {message.role === "assistant"
                              ? "Nexa AI"
                              : "You"}
                          </div>

                          <div className="message-content">
                            {message.role === "assistant" ? (
                              <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={{
                                  a: ({
                                    href,
                                    children,
                                    ...props
                                  }) => (
                                    <a
                                      href={href}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      {...props}
                                    >
                                      {children}
                                    </a>
                                  ),
                                }}
                              >
                                {message.content}
                              </ReactMarkdown>
                            ) : (
                              message.content
                            )}
                          </div>
                        </div>
                      </div>
                    ))}

                    {loading && (
                      <div className="loading-message">
                        <LoaderCircle
                          size={18}
                          className="spin"
                        />
                        <span>AI is thinking...</span>
                      </div>
                    )}
                  </div>
                )}

                <div className="composer-wrap">
                  <div className="composer">
                    <button
                      type="button"
                      className="composer-attach"
                      aria-label="Ouvrir la Knowledge Base"
                      title="Knowledge Base"
                      onClick={() =>
                        setActiveTab("Knowledge Base")
                      }
                    >
                      <Paperclip size={19} />
                    </button>

                    <textarea
                      value={question}
                      onChange={(event) =>
                        setQuestion(event.target.value)
                      }
                      onKeyDown={handleComposerKeyDown}
                      placeholder="Message Nexa AI..."
                      rows={1}
                    />

                    <button
                      type="button"
                      className="send-button"
                      onClick={() => void sendMessage()}
                      disabled={!question.trim() || loading}
                      aria-label="Envoyer le message"
                    >
                      {loading ? (
                        <LoaderCircle
                          size={19}
                          className="spin"
                        />
                      ) : (
                        <ArrowUp size={21} />
                      )}
                    </button>
                  </div>

                  <div className="composer-footer">
                    <span>
                      <Sparkles size={13} />
                      AI can make mistakes. Verify important
                      information.
                    </span>
                    <span>
                      Enter to send · Shift + Enter for a new
                      line
                    </span>
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* KNOWLEDGE BASE */}

          {activeTab === "Knowledge Base" && (
            <section>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    <BookOpen size={14} />
                    YOUR DOCUMENTS
                  </div>

                  <h1>Knowledge Base</h1>

                  <p>
                    Upload PDFs and build a searchable knowledge
                    base for your AI assistant.
                  </p>
                </div>

                <button
                  type="button"
                  className="primary-button"
                  onClick={() => fileRef.current?.click()}
                >
                  <UploadCloud size={17} />
                  Upload PDF
                </button>
              </div>

              <div
                className="upload-zone"
                onClick={() => fileRef.current?.click()}
                onDragOver={(event) =>
                  event.preventDefault()
                }
                onDrop={(event) => {
                  event.preventDefault();
                  void handleFileSelect(
                    event.dataTransfer.files
                  );
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" ||
                    event.key === " "
                  ) {
                    event.preventDefault();
                    fileRef.current?.click();
                  }
                }}
              >
                <div className="upload-icon">
                  <UploadCloud size={27} />
                </div>

                <h3>Drop your PDF files here</h3>
                <p>or click to browse your computer</p>

                <span className="file-format">
                  PDF files only · Maximum 20 MB per file
                </span>

                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  multiple
                  hidden
                  onClick={(event) =>
                    event.stopPropagation()
                  }
                  onChange={(event) => {
                    const input = event.currentTarget;
                    const files = input.files
                      ? Array.from(input.files)
                      : [];

                    input.value = "";
                    void handleFileSelect(files);
                  }}
                />
              </div>

              <div className="section-title-row">
                <div>
                  <h2>Your documents</h2>
                  <p>
                    {documents.length} document(s) in this
                    workspace
                  </p>
                </div>

                <button
                  type="button"
                  className="outline-button"
                  onClick={() => void loadDocuments()}
                  disabled={documentsLoading}
                >
                  {documentsLoading ? (
                    <LoaderCircle
                      size={16}
                      className="spin"
                    />
                  ) : (
                    <History size={16} />
                  )}
                  Actualiser
                </button>
              </div>

              <div className="document-list">
                {documentsLoading && documents.length === 0 ? (
                  <div className="empty-documents">
                    Chargement des documents...
                  </div>
                ) : documents.length === 0 ? (
                  <div className="empty-documents">
                    No documents yet. Upload a PDF to get
                    started.
                  </div>
                ) : (
                  documents.map((doc) => (
                    <div
                      className="document-row"
                      key={doc.id}
                    >
                      <div className="pdf-icon">
                        <FileText size={22} />
                      </div>

                      <div className="document-info">
                        <strong>{doc.name}</strong>
                        <span>PDF document</span>

                        {doc.chunksIndexed !== undefined && (
                          <span>
                            {doc.chunksIndexed} chunks indexés
                          </span>
                        )}

                        {doc.error && (
                          <span
                            className="auth-error"
                            role="alert"
                          >
                            {doc.error}
                          </span>
                        )}
                      </div>

                      <span
                        className={`document-status ${doc.status.toLowerCase()}`}
                        role="status"
                      >
                        <span
                          className="document-status-icon"
                          aria-hidden="true"
                        >
                          {doc.status === "Indexed"
                            ? "✓"
                            : doc.status === "Processing"
                              ? "…"
                              : "!"}
                        </span>
                        <span>{doc.status}</span>
                      </span>
                    </div>
                  ))
                )}
              </div>

              <div className="knowledge-notice">
                Les fichiers PDF sont envoyés au serveur FastAPI
                pour être indexés. Après l'indexation, vous pouvez
                poser des questions sur leur contenu dans Chat
                Workspace.
              </div>
            </section>
          )}

          {/* WEB RESEARCH */}

          {activeTab === "Web Research" && (
            <section>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    <Globe size={14} />
                    ONLINE DISCOVERY
                  </div>

                  <h1>Web Research</h1>

                  <p>
                    Search the web and explore the sources behind
                    your AI answers.
                  </p>
                </div>
              </div>

              <div className="research-card">
                <div className="research-icon">
                  <Globe size={26} />
                </div>

                <h2>Research with confidence</h2>

                <p>
                  Pose une question à ton assistant. Les résultats
                  web dépendront de l'intégration Tavily dans ton
                  agent.
                </p>

                <button
                  type="button"
                  className="primary-button"
                  onClick={() => {
                    setActiveTab("Chat Workspace");
                    setQuestion(
                      "Search the web for recent AI research"
                    );
                  }}
                >
                  <Search size={17} />
                  Start web research
                </button>
              </div>

              <div className="sources-note">
                <div className="sources-note-icon">
                  <FileText size={19} />
                </div>

                <div>
                  <strong>Sources and citations</strong>
                  <p>
                    Les liens et titres des sources seront
                    affichés lorsque le backend renverra les
                    métadonnées correspondantes.
                  </p>
                </div>
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

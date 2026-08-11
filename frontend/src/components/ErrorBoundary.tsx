import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Filet de securite : sans ceci, une exception de rendu (ex. reponse API de
 * forme inattendue) demonte tout l'arbre React et laisse une page blanche
 * silencieuse, sans indice pour l'utilisateur ni moyen de s'en sortir sans
 * recharger a l'aveugle. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("nfogen: erreur de rendu non rattrapee", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-lg space-y-3 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p className="font-medium">Une erreur inattendue est survenue.</p>
          <p className="break-words text-red-600">{this.state.error.message}</p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="rounded-md bg-red-700 px-3 py-1.5 text-white hover:bg-red-800"
          >
            Reessayer
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

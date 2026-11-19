import { c } from "./i18n";

export const tabs = [
  {
    id: "profile",
    path: "",
    label: c("Profile", "Profilo", "Perfil", "Perfil", "Profil"),
  },
  {
    id: "match",
    path: "/match-interpretation",
    label: c(
      "Match interpretation",
      "Lettura della partita",
      "Interpretación del partido",
      "Interpretação do jogo",
      "Lecture du match",
    ),
  },
  {
    id: "beliefs",
    path: "/beliefs",
    label: c(
      "Coaching beliefs",
      "Convinzioni",
      "Convicciones",
      "Convicções",
      "Convictions",
    ),
  },
  {
    id: "training",
    path: "/training",
    label: c(
      "Training drills",
      "Esercitazioni",
      "Ejercicios",
      "Exercícios",
      "Exercices",
    ),
  },
  {
    id: "identity",
    path: "/player-identity",
    label: c(
      "Player identity",
      "Identità del giocatore",
      "Identidad del jugador",
      "Identidade do jogador",
      "Identité du joueur",
    ),
  },
] as const;

export type TabId = (typeof tabs)[number]["id"];

export const ui = {
  skip: c(
    "Skip to content",
    "Vai al contenuto",
    "Ir al contenido",
    "Ir para o conteúdo",
    "Aller au contenu",
  ),
  language: c("Language", "Lingua", "Idioma", "Idioma", "Langue"),
  sections: c("Sections", "Sezioni", "Secciones", "Secções", "Rubriques"),
  cv: c("One-page CV", "CV in una pagina", "CV en una página", "CV numa página", "CV en une page"),
  print: c(
    "Print / save as PDF",
    "Stampa / salva in PDF",
    "Imprimir / guardar en PDF",
    "Imprimir / guardar em PDF",
    "Imprimer / enregistrer en PDF",
  ),
  backToSite: c(
    "Back to site",
    "Torna al sito",
    "Volver al sitio",
    "Voltar ao site",
    "Retour au site",
  ),
  open: c("Open", "Apri", "Abrir", "Abrir", "Ouvrir"),
  present: c("present", "oggi", "actualidad", "presente", "aujourd’hui"),
  since: c("Since", "Dal", "Desde", "Desde", "Depuis"),
  inPreparationTitle: c(
    "In preparation",
    "In preparazione",
    "En preparación",
    "Em preparação",
    "En préparation",
  ),
  inPreparationBody: c(
    "Antonio’s own notes and the video clips for this section are being added.",
    "Le note di Antonio e i video di questa sezione sono in fase di inserimento.",
    "Las notas de Antonio y los vídeos de esta sección se están añadiendo.",
    "As notas do Antonio e os vídeos desta secção estão a ser adicionados.",
    "Les notes d’Antonio et les vidéos de cette rubrique sont en cours d’ajout.",
  ),
  textToCome: c(
    "Antonio’s notes to come",
    "Note di Antonio in arrivo",
    "Notas de Antonio próximamente",
    "Notas do Antonio em breve",
    "Notes d’Antonio à venir",
  ),
  videoToCome: c(
    "Video to come",
    "Video in arrivo",
    "Vídeo próximamente",
    "Vídeo em breve",
    "Vidéo à venir",
  ),
  playVideo: c(
    "Play video",
    "Riproduci il video",
    "Reproducir el vídeo",
    "Reproduzir o vídeo",
    "Lire la vidéo",
  ),
  notFoundTitle: c(
    "This page is not on the team sheet.",
    "Questa pagina non è in distinta.",
    "Esta página no está en la convocatoria.",
    "Esta página não está na convocatória.",
    "Cette page n’est pas sur la feuille de match.",
  ),
  notFoundBody: c(
    "The address may have changed. The profile page is the best place to start again.",
    "L’indirizzo potrebbe essere cambiato. Il profilo è il punto migliore da cui ripartire.",
    "Puede que la dirección haya cambiado. El perfil es el mejor punto para volver a empezar.",
    "O endereço pode ter mudado. O perfil é o melhor ponto para recomeçar.",
    "L’adresse a peut-être changé. Le profil est le meilleur point de départ.",
  ),
  notFoundAction: c(
    "Go to the profile",
    "Vai al profilo",
    "Ir al perfil",
    "Ir para o perfil",
    "Aller au profil",
  ),
  year: c("year", "anno", "año", "ano", "an"),
  years: c("years", "anni", "años", "anos", "ans"),
  month: c("month", "mese", "mes", "mês", "mois"),
  months: c("months", "mesi", "meses", "meses", "mois"),
};

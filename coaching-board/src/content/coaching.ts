import { c, type Copy } from "./i18n";

/**
 * The four coaching tabs.
 *
 * Text: a field left as `null` shows "Antonio's notes to come" on the page.
 * Replace it with c("English", "Italiano", "Español", "Português", "Français").
 *
 * Video: a field left as `null` shows an empty frame. Replace it with a link:
 *   "https://vimeo.com/123456789"            Vimeo (unlisted links with a hash also work)
 *   "https://youtu.be/abcdefghijk"           YouTube
 *   "/videos/pressing-drill.mp4"             a file placed in public/videos
 */

export type Text = Copy | null;
export type VideoLink = string | null;

/* ------------------------------------------------------------------ */
/* Match interpretation                                                */
/* ------------------------------------------------------------------ */

export type MatchMoment = { id: string; title: Copy; notes: Text };

export type MatchPhase = {
  id: string;
  title: Copy;
  video: VideoLink;
  videoCaption: Text;
  moments: MatchMoment[];
};

export const matchInterpretation = {
  title: c(
    "Match interpretation",
    "Lettura della partita",
    "Interpretación del partido",
    "Interpretação do jogo",
    "Lecture du match",
  ),
  intro: c(
    "How the team is asked to read the match, phase by phase, with clips from games.",
    "Come la squadra è chiamata a leggere la partita, fase per fase, con clip di gara.",
    "Cómo se le pide al equipo que lea el partido, fase a fase, con clips de los encuentros.",
    "Como se pede à equipa que leia o jogo, fase a fase, com clips dos jogos.",
    "Comment l’équipe doit lire le match, phase par phase, avec des séquences de match.",
  ),
  clipLabel: c("Match clip", "Clip di gara", "Clip del partido", "Clip do jogo", "Séquence de match"),
  phases: [
    {
      id: "in-possession",
      title: c("In possession", "Fase di possesso", "Con balón", "Com bola", "Avec le ballon"),
      video: null,
      videoCaption: null,
      moments: [
        {
          id: "build-up",
          title: c("Build-up", "Costruzione", "Salida de balón", "Construção", "Relance"),
          notes: null,
        },
        {
          id: "progression",
          title: c("Progression", "Sviluppo", "Progresión", "Progressão", "Progression"),
          notes: null,
        },
        {
          id: "final-third",
          title: c(
            "Final third",
            "Rifinitura e finalizzazione",
            "Último tercio",
            "Último terço",
            "Dernier tiers",
          ),
          notes: null,
        },
      ],
    },
    {
      id: "out-of-possession",
      title: c(
        "Out of possession",
        "Fase di non possesso",
        "Sin balón",
        "Sem bola",
        "Sans le ballon",
      ),
      video: null,
      videoCaption: null,
      moments: [
        {
          id: "high-press",
          title: c("High press", "Pressione alta", "Presión alta", "Pressão alta", "Pressing haut"),
          notes: null,
        },
        {
          id: "mid-block",
          title: c("Mid block", "Blocco medio", "Bloque medio", "Bloco médio", "Bloc médian"),
          notes: null,
        },
        {
          id: "defending-the-box",
          title: c(
            "Defending the box",
            "Difesa dell’area",
            "Defensa del área",
            "Defesa da área",
            "Défense de la surface",
          ),
          notes: null,
        },
      ],
    },
    {
      id: "transitions",
      title: c("Transitions", "Transizioni", "Transiciones", "Transições", "Transitions"),
      video: null,
      videoCaption: null,
      moments: [
        {
          id: "ball-won",
          title: c(
            "After winning the ball",
            "Palla riconquistata",
            "Tras recuperar el balón",
            "Após recuperar a bola",
            "À la récupération du ballon",
          ),
          notes: null,
        },
        {
          id: "ball-lost",
          title: c(
            "After losing the ball",
            "Palla persa",
            "Tras perder el balón",
            "Após perder a bola",
            "À la perte du ballon",
          ),
          notes: null,
        },
      ],
    },
    {
      id: "set-pieces",
      title: c(
        "Set pieces",
        "Palle inattive",
        "Balón parado",
        "Bolas paradas",
        "Coups de pied arrêtés",
      ),
      video: null,
      videoCaption: null,
      moments: [
        {
          id: "set-pieces-for",
          title: c("Attacking", "A favore", "Ofensivo", "Ofensivas", "Offensifs"),
          notes: null,
        },
        {
          id: "set-pieces-against",
          title: c("Defending", "Contro", "Defensivo", "Defensivas", "Défensifs"),
          notes: null,
        },
      ],
    },
  ] as MatchPhase[],
};

/* ------------------------------------------------------------------ */
/* Coaching beliefs                                                    */
/* ------------------------------------------------------------------ */

export type Belief = { id: string; theme: Copy; statement: Text; body: Text };

export const beliefs = {
  title: c(
    "Coaching beliefs",
    "Convinzioni",
    "Convicciones",
    "Convicções",
    "Convictions",
  ),
  intro: c(
    "What Antonio holds to, whatever the team, the level or the result.",
    "Ciò a cui Antonio resta fedele, qualunque sia la squadra, la categoria o il risultato.",
    "Aquello a lo que Antonio se mantiene fiel, sea cual sea el equipo, la categoría o el resultado.",
    "Aquilo a que o Antonio se mantém fiel, seja qual for a equipa, o nível ou o resultado.",
    "Ce à quoi Antonio reste fidèle, quels que soient l’équipe, le niveau ou le résultat.",
  ),
  /** The opening line of the page, in his own words. */
  openingStatement: null as Text,
  openingLabel: c(
    "Opening statement",
    "Dichiarazione d’apertura",
    "Declaración inicial",
    "Declaração inicial",
    "Déclaration d’ouverture",
  ),
  items: [
    {
      id: "player",
      theme: c("The player", "Il giocatore", "El jugador", "O jogador", "Le joueur"),
      statement: null,
      body: null,
    },
    {
      id: "team",
      theme: c("The team", "La squadra", "El equipo", "A equipa", "L’équipe"),
      statement: null,
      body: null,
    },
    {
      id: "training",
      theme: c("The training week", "La settimana di lavoro", "La semana de trabajo", "A semana de trabalho", "La semaine de travail"),
      statement: null,
      body: null,
    },
    {
      id: "match",
      theme: c("The match", "La partita", "El partido", "O jogo", "Le match"),
      statement: null,
      body: null,
    },
    {
      id: "staff",
      theme: c("The staff", "Lo staff", "El cuerpo técnico", "A equipa técnica", "Le staff"),
      statement: null,
      body: null,
    },
    {
      id: "development",
      theme: c(
        "Development",
        "La crescita",
        "El desarrollo",
        "O desenvolvimento",
        "La progression",
      ),
      statement: null,
      body: null,
    },
  ] as Belief[],
};

/* ------------------------------------------------------------------ */
/* Training drills                                                     */
/* ------------------------------------------------------------------ */

export type Drill = {
  id: string;
  title: Copy;
  /** Short facts about the set-up: numbers, space, time. */
  setup: { label: Copy; value: Copy }[];
  objective: Text;
  coachingPoints: Text[];
  trainingVideo: VideoLink;
  matchVideo: VideoLink;
  /** One line on what to look for in the match clip. */
  matchNote: Text;
};

const label = {
  format: c("Format", "Formato", "Formato", "Formato", "Format"),
  space: c("Space", "Spazio", "Espacio", "Espaço", "Espace"),
  time: c("Time", "Durata", "Duración", "Duração", "Durée"),
};

export const training = {
  title: c(
    "Training drills",
    "Esercitazioni",
    "Ejercicios de entrenamiento",
    "Exercícios de treino",
    "Exercices d’entraînement",
  ),
  intro: c(
    "Each exercise is shown twice: first on the training pitch, then in the match it was built for.",
    "Ogni esercitazione si vede due volte: prima in allenamento, poi nella partita per cui è stata pensata.",
    "Cada ejercicio se ve dos veces: primero en el entrenamiento y después en el partido para el que se diseñó.",
    "Cada exercício é mostrado duas vezes: primeiro no treino, depois no jogo para o qual foi pensado.",
    "Chaque exercice est montré deux fois : d’abord à l’entraînement, puis dans le match pour lequel il a été conçu.",
  ),
  trainingLabel: c(
    "On the training pitch",
    "In allenamento",
    "En el entrenamiento",
    "No treino",
    "À l’entraînement",
  ),
  matchLabel: c("In the match", "In partita", "En el partido", "No jogo", "En match"),
  objectiveLabel: c("Objective", "Obiettivo", "Objetivo", "Objetivo", "Objectif"),
  pointsLabel: c(
    "Coaching points",
    "Punti chiave",
    "Puntos clave",
    "Pontos-chave",
    "Points clés",
  ),
  /* Names and set-ups are taken from the Napoli Under-19 session plans of September 2026. */
  drills: [
    {
      id: "4v2",
      title: c(
        "4v2 technical activation",
        "Attivazione tecnica 4 contro 2",
        "Activación técnica 4 contra 2",
        "Ativação técnica 4 contra 2",
        "Activation technique à 4 contre 2",
      ),
      setup: [
        { label: label.format, value: c("4v2", "4 vs 2", "4 vs 2", "4 vs 2", "4 contre 2") },
        {
          label: label.time,
          value: c(
            "6 repetitions of 1′30″",
            "6 ripetizioni da 1′30″",
            "6 repeticiones de 1′30″",
            "6 repetições de 1′30″",
            "6 répétitions de 1′30″",
          ),
        },
      ],
      objective: null,
      coachingPoints: [null, null, null],
      trainingVideo: null,
      matchVideo: null,
      matchNote: null,
    },
    {
      id: "pressing-games",
      title: c(
        "Pressing games, mini-tournament",
        "Partite a pressione, mini torneo",
        "Partidos de presión, minitorneo",
        "Jogos de pressão, minitorneio",
        "Matchs à pression, mini-tournoi",
      ),
      setup: [
        {
          label: label.format,
          value: c(
            "3 teams, two rounds",
            "3 squadre, andata e ritorno",
            "3 equipos, ida y vuelta",
            "3 equipas, ida e volta",
            "3 équipes, aller et retour",
          ),
        },
        {
          label: label.time,
          value: c(
            "3-minute games, 18′ in total",
            "Partite da 3′, 18′ in totale",
            "Partidos de 3′, 18′ en total",
            "Jogos de 3′, 18′ no total",
            "Matchs de 3′, 18′ au total",
          ),
        },
      ],
      objective: null,
      coachingPoints: [null, null, null],
      trainingVideo: null,
      matchVideo: null,
      matchNote: null,
    },
    {
      id: "attack-v-defence",
      title: c(
        "Attack against defence",
        "Attacco contro difesa",
        "Ataque contra defensa",
        "Ataque contra defesa",
        "Attaque contre défense",
      ),
      setup: [
        {
          label: label.format,
          value: c(
            "8v6, then 10v8",
            "8 vs 6, poi 10 vs 8",
            "8 vs 6, después 10 vs 8",
            "8 vs 6, depois 10 vs 8",
            "8 contre 6, puis 10 contre 8",
          ),
        },
        { label: label.time, value: c("20′", "20′", "20′", "20′", "20′") },
      ],
      objective: null,
      coachingPoints: [null, null, null],
      trainingVideo: null,
      matchVideo: null,
      matchNote: null,
    },
    {
      id: "tactical-possession",
      title: c(
        "Tactical possession",
        "Possesso tattico",
        "Posesión táctica",
        "Posse tática",
        "Possession tactique",
      ),
      setup: [
        { label: label.space, value: c("40 × 40 m", "40 × 40 m", "40 × 40 m", "40 × 40 m", "40 × 40 m") },
        { label: label.time, value: c("20′", "20′", "20′", "20′", "20′") },
      ],
      objective: null,
      coachingPoints: [null, null, null],
      trainingVideo: null,
      matchVideo: null,
      matchNote: null,
    },
  ] as Drill[],
};

/* ------------------------------------------------------------------ */
/* Player identity                                                     */
/* ------------------------------------------------------------------ */

export type Role = {
  id: string;
  title: Copy;
  /** Where the role stands on the pitch diagram, as percentages (x from the left, y from the top; the team attacks upwards). */
  spots: { x: number; y: number }[];
  withBall: Text;
  withoutBall: Text;
  character: Text;
};

export const identity = {
  title: c(
    "Player identity",
    "Identità del giocatore",
    "Identidad del jugador",
    "Identidade do jogador",
    "Identité du joueur",
  ),
  intro: c(
    "What each position is asked to be: with the ball, without it, and as a person in the group.",
    "Che cosa si chiede a ogni ruolo: con la palla, senza, e come persona nel gruppo.",
    "Lo que se le pide a cada puesto: con balón, sin balón y como persona dentro del grupo.",
    "O que se pede a cada posição: com bola, sem bola e como pessoa dentro do grupo.",
    "Ce qui est demandé à chaque poste : avec le ballon, sans le ballon et comme personne dans le groupe.",
  ),
  /** The shape written on the Napoli Under-19 session plans. Change the label and the spots together. */
  formation: "3-4-2-1",
  formationLabel: c("Shape", "Modulo", "Sistema", "Sistema", "Système"),
  pickLabel: c(
    "Choose a position",
    "Scegli un ruolo",
    "Elige un puesto",
    "Escolha uma posição",
    "Choisissez un poste",
  ),
  withBallLabel: c("With the ball", "Con la palla", "Con balón", "Com bola", "Avec le ballon"),
  withoutBallLabel: c("Without the ball", "Senza palla", "Sin balón", "Sem bola", "Sans le ballon"),
  characterLabel: c("Character", "Carattere", "Carácter", "Carácter", "Caractère"),
  roles: [
    {
      id: "goalkeeper",
      title: c("Goalkeeper", "Portiere", "Portero", "Guarda-redes", "Gardien de but"),
      spots: [{ x: 50, y: 91 }],
      withBall: null,
      withoutBall: null,
      character: null,
    },
    {
      id: "wide-centre-backs",
      title: c(
        "Wide centre-backs",
        "Braccetti",
        "Centrales exteriores",
        "Centrais exteriores",
        "Défenseurs centraux excentrés",
      ),
      spots: [
        { x: 24, y: 74 },
        { x: 76, y: 74 },
      ],
      withBall: null,
      withoutBall: null,
      character: null,
    },
    {
      id: "central-centre-back",
      title: c(
        "Central centre-back",
        "Difensore centrale",
        "Central del medio",
        "Central do meio",
        "Défenseur central axial",
      ),
      spots: [{ x: 50, y: 78 }],
      withBall: null,
      withoutBall: null,
      character: null,
    },
    {
      id: "wing-backs",
      title: c("Wing-backs", "Quinti", "Carrileros", "Alas", "Pistons"),
      spots: [
        { x: 10, y: 50 },
        { x: 90, y: 50 },
      ],
      withBall: null,
      withoutBall: null,
      character: null,
    },
    {
      id: "central-midfielders",
      title: c(
        "Central midfielders",
        "Centrocampisti centrali",
        "Mediocentros",
        "Médios-centro",
        "Milieux axiaux",
      ),
      spots: [
        { x: 37, y: 55 },
        { x: 63, y: 55 },
      ],
      withBall: null,
      withoutBall: null,
      character: null,
    },
    {
      id: "attacking-midfielders",
      title: c(
        "Attacking midfielders",
        "Trequartisti",
        "Mediapuntas",
        "Médios ofensivos",
        "Milieux offensifs",
      ),
      spots: [
        { x: 32, y: 31 },
        { x: 68, y: 31 },
      ],
      withBall: null,
      withoutBall: null,
      character: null,
    },
    {
      id: "striker",
      title: c("Striker", "Centravanti", "Delantero centro", "Ponta de lança", "Avant-centre"),
      spots: [{ x: 50, y: 15 }],
      withBall: null,
      withoutBall: null,
      character: null,
    },
  ] as Role[],
};

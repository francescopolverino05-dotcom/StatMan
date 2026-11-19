import { c, type Copy } from "./i18n";

/**
 * Everything on the Profile tab and the one-page CV.
 * Coaching dates follow Antonio's Transfermarkt coaching profile:
 * https://www.transfermarkt.it/antonio-nocerino/profil/trainer/76468
 */

export const site = {
  name: "Antonio Nocerino",
  initials: "AN",
  /** Shows the "In preparation" strip on the four coaching tabs. Set to false once his content is in. */
  inPreparation: true,
  /** Path under /public (for example "/antonio.jpg"). Empty shows the monogram card instead. */
  photo: "/antonio-nocerino.jpg",
  role: c(
    "Head coach, SSC Napoli Under-19",
    "Allenatore, SSC Napoli Under 19",
    "Entrenador, SSC Napoli Sub-19",
    "Treinador, SSC Napoli Sub-19",
    "Entraîneur, SSC Napoli U19",
  ),
  kicker: c(
    "Head coach · UEFA Pro Licence · Former Italy international",
    "Allenatore · Licenza UEFA Pro · Ex nazionale italiano",
    "Entrenador · Licencia UEFA Pro · Exinternacional italiano",
    "Treinador · Licença UEFA Pro · Ex-internacional italiano",
    "Entraîneur · Licence UEFA Pro · Ancien international italien",
  ),
  lede: c(
    "A midfielder in Serie A, the Champions League and Italy’s national team, and a coach from the day after he stopped playing. Academy football in Orlando and Potenza, senior head-coach roles in the United States with Miami FC and Las Vegas Lights, and now Napoli’s Under-19s.",
    "Centrocampista in Serie A, in Champions League e in Nazionale, allenatore dal giorno dopo il ritiro. Settore giovanile a Orlando e a Potenza, prime squadre negli Stati Uniti con Miami FC e Las Vegas Lights, oggi l’Under 19 del Napoli.",
    "Centrocampista en la Serie A, la Champions League y la selección italiana, y entrenador desde el día siguiente a su retirada. Fútbol formativo en Orlando y Potenza, primeros equipos en Estados Unidos con Miami FC y Las Vegas Lights, y ahora el Sub-19 del Napoli.",
    "Médio na Serie A, na Liga dos Campeões e na seleção italiana, e treinador desde o dia seguinte ao fim da carreira. Futebol de formação em Orlando e em Potenza, equipas principais nos Estados Unidos com o Miami FC e o Las Vegas Lights, e agora os Sub-19 do Napoli.",
    "Milieu de terrain en Serie A, en Ligue des champions et en équipe d’Italie, entraîneur dès le lendemain de sa retraite. La formation à Orlando et à Potenza, des équipes premières aux États-Unis avec le Miami FC et les Las Vegas Lights, et aujourd’hui les U19 de Naples.",
  ),
  /** Leave a field empty to hide it. With every field empty the contact block says details are on their way. */
  contact: {
    email: "",
    phone: "",
    linkedin: "",
    /** Agent or representative, shown as plain text. */
    representation: "",
  },
  /** Temporary. Remove this credit once the CV is finished. */
  credit: {
    label: c(
      "Site and analysis by Francesco Polverino",
      "Sito e analisi di Francesco Polverino",
      "Sitio y análisis de Francesco Polverino",
      "Site e análise de Francesco Polverino",
      "Site et analyse par Francesco Polverino",
    ),
    href: "https://francesco-polverino.apps.grok.bot",
  },
};

export const heroFacts: { label: Copy; value: Copy }[] = [
  {
    label: c("Now", "Oggi", "Ahora", "Agora", "Aujourd’hui"),
    value: c(
      "SSC Napoli Under-19 · Head coach",
      "SSC Napoli Under 19 · Allenatore",
      "SSC Napoli Sub-19 · Entrenador",
      "SSC Napoli Sub-19 · Treinador",
      "SSC Napoli U19 · Entraîneur",
    ),
  },
  {
    label: c("Licence", "Licenza", "Licencia", "Licença", "Licence"),
    value: c("UEFA Pro", "UEFA Pro", "UEFA Pro", "UEFA Pro", "UEFA Pro"),
  },
  {
    label: c(
      "Season 2026/27",
      "Stagione 2026/27",
      "Temporada 2026/27",
      "Época 2026/27",
      "Saison 2026/27",
    ),
    value: c(
      "Primavera 2 · UEFA Youth League · Coppa Italia Primavera",
      "Primavera 2 · UEFA Youth League · Coppa Italia Primavera",
      "Primavera 2 · UEFA Youth League · Coppa Italia Primavera",
      "Primavera 2 · UEFA Youth League · Coppa Italia Primavera",
      "Primavera 2 · UEFA Youth League · Coppa Italia Primavera",
    ),
  },
  {
    label: c("As a player", "Da calciatore", "Como jugador", "Como jogador", "Comme joueur"),
    value: c(
      "Midfielder · 15 caps for Italy",
      "Centrocampista · 15 presenze in Nazionale",
      "Centrocampista · 15 partidos con Italia",
      "Médio · 15 internacionalizações por Itália",
      "Milieu de terrain · 15 sélections avec l’Italie",
    ),
  },
];

export const profile = {
  kicker: c("01 — Profile", "01 — Profilo", "01 — Perfil", "01 — Perfil", "01 — Profil"),
  title: c("Who he is", "Chi è", "Quién es", "Quem é", "Qui il est"),
  lead: c(
    "A Neapolitan coaching Napoli’s Under-19s, with a playing career at the top of the game and six years of coaching on two continents behind him.",
    "Un napoletano alla guida dell’Under 19 del Napoli, con una carriera da calciatore ai massimi livelli e sei anni di panchina in due continenti.",
    "Un napolitano al frente del Sub-19 del Napoli, con una carrera como jugador en la élite y seis años de banquillo en dos continentes.",
    "Um napolitano à frente dos Sub-19 do Napoli, com uma carreira de jogador ao mais alto nível e seis anos de banco em dois continentes.",
    "Un Napolitain à la tête des U19 de Naples, avec une carrière de joueur au plus haut niveau et six ans de banc sur deux continents.",
  ),
  paragraphs: [
    c(
      "Antonio Nocerino has been head coach of SSC Napoli’s Under-19s since July 2026. This season the team plays in Primavera 2, the UEFA Youth League and the Coppa Italia Primavera.",
      "Antonio Nocerino è l’allenatore dell’Under 19 della SSC Napoli da luglio 2026. In questa stagione la squadra gioca in Primavera 2, in UEFA Youth League e in Coppa Italia Primavera.",
      "Antonio Nocerino es el entrenador del Sub-19 de la SSC Napoli desde julio de 2026. Esta temporada el equipo compite en la Primavera 2, la UEFA Youth League y la Coppa Italia Primavera.",
      "Antonio Nocerino é o treinador dos Sub-19 da SSC Napoli desde julho de 2026. Esta época a equipa disputa a Primavera 2, a UEFA Youth League e a Coppa Italia Primavera.",
      "Antonio Nocerino entraîne les U19 de la SSC Napoli depuis juillet 2026. Cette saison, l’équipe dispute la Primavera 2, l’UEFA Youth League et la Coppa Italia Primavera.",
    ),
    c(
      "His coaching path began in January 2020 in the Orlando City academy, the day after his playing career ended. Two and a half years there were followed by a season leading Potenza’s youth sector and Under-19s, then two senior head-coach roles in the USL Championship, with Miami FC and Las Vegas Lights.",
      "Il suo percorso in panchina è iniziato a gennaio 2020 nell’academy dell’Orlando City, il giorno dopo la fine della carriera da calciatore. Dopo due anni e mezzo è arrivata una stagione alla guida del settore giovanile e dell’Under 19 del Potenza, poi due incarichi da allenatore di prima squadra in USL Championship, con Miami FC e Las Vegas Lights.",
      "Su camino en los banquillos empezó en enero de 2020 en la academia del Orlando City, al día siguiente de terminar su carrera como jugador. Tras dos años y medio llegó una temporada al frente del fútbol base y del Sub-19 del Potenza, y después dos etapas como primer entrenador en la USL Championship, con Miami FC y Las Vegas Lights.",
      "O seu percurso como treinador começou em janeiro de 2020 na academia do Orlando City, no dia seguinte ao fim da carreira de jogador. Depois de dois anos e meio seguiu-se uma época à frente da formação e dos Sub-19 do Potenza, e depois duas passagens como treinador principal na USL Championship, no Miami FC e no Las Vegas Lights.",
      "Son parcours d’entraîneur a commencé en janvier 2020 à l’académie d’Orlando City, le lendemain de la fin de sa carrière de joueur. Après deux ans et demi sont venues une saison à la tête du secteur jeunes et des U19 de Potenza, puis deux postes d’entraîneur principal en USL Championship, au Miami FC et aux Las Vegas Lights.",
    ),
    c(
      "Before that he was a professional midfielder from 2003 to 2020, with Palermo, AC Milan, Juventus, West Ham United, Torino and Orlando City among his clubs, and won 15 caps for Italy, finishing runner-up at Euro 2012.",
      "Prima è stato centrocampista professionista dal 2003 al 2020, con Palermo, Milan, Juventus, West Ham United, Torino e Orlando City tra le sue squadre, e ha collezionato 15 presenze in Nazionale, da vicecampione d’Europa a Euro 2012.",
      "Antes fue centrocampista profesional de 2003 a 2020, con Palermo, AC Milan, Juventus, West Ham United, Torino y Orlando City entre sus clubes, y disputó 15 partidos con Italia, subcampeona de la Eurocopa 2012.",
      "Antes foi médio profissional de 2003 a 2020, com Palermo, AC Milan, Juventus, West Ham United, Torino e Orlando City entre os seus clubes, e somou 15 internacionalizações por Itália, vice-campeã do Euro 2012.",
      "Auparavant, il a été milieu de terrain professionnel de 2003 à 2020, avec Palerme, l’AC Milan, la Juventus, West Ham United, le Torino et Orlando City parmi ses clubs, et compte 15 sélections avec l’Italie, finaliste de l’Euro 2012.",
    ),
  ],
  facts: [
    {
      label: c("Born", "Nato", "Nacimiento", "Nascimento", "Naissance"),
      value: c(
        "Naples, 9 April 1985",
        "Napoli, 9 aprile 1985",
        "Nápoles, 9 de abril de 1985",
        "Nápoles, 9 de abril de 1985",
        "Naples, 9 avril 1985",
      ),
    },
    {
      label: c("Licence", "Licenza", "Licencia", "Licença", "Licence"),
      value: c("UEFA Pro", "UEFA Pro", "UEFA Pro", "UEFA Pro", "UEFA Pro"),
    },
    {
      label: c(
        "Coaching since",
        "In panchina dal",
        "Entrenador desde",
        "Treinador desde",
        "Entraîneur depuis",
      ),
      value: c(
        "January 2020",
        "gennaio 2020",
        "enero de 2020",
        "janeiro de 2020",
        "janvier 2020",
      ),
    },
  ],
};

export const method = {
  kicker: c("02 — Method", "02 — Metodo", "02 — Método", "02 — Método", "02 — Méthode"),
  title: c(
    "How he works",
    "Come lavora",
    "Cómo trabaja",
    "Como trabalha",
    "Comment il travaille",
  ),
  intro: c(
    "Four chapters, each with its own page.",
    "Quattro capitoli, ognuno con la sua pagina.",
    "Cuatro capítulos, cada uno con su página.",
    "Quatro capítulos, cada um com a sua página.",
    "Quatre chapitres, chacun avec sa page.",
  ),
  cards: {
    match: c(
      "How each moment of the match is read: with the ball, without it, in transition and at set pieces.",
      "Come viene letto ogni momento della gara: con la palla, senza, in transizione e sulle palle inattive.",
      "Cómo se lee cada momento del partido: con balón, sin balón, en transición y a balón parado.",
      "Como se lê cada momento do jogo: com bola, sem bola, em transição e nas bolas paradas.",
      "Comment chaque moment du match est lu : avec le ballon, sans le ballon, en transition et sur coups de pied arrêtés.",
    ),
    beliefs: c(
      "The convictions behind the work, in his own words.",
      "Le convinzioni dietro al lavoro, con le sue parole.",
      "Las convicciones que hay detrás del trabajo, con sus propias palabras.",
      "As convicções por detrás do trabalho, nas suas próprias palavras.",
      "Les convictions derrière le travail, avec ses propres mots.",
    ),
    training: c(
      "The exercises, filmed on the training pitch and then shown again in the match.",
      "Le esercitazioni, filmate in allenamento e poi riviste in partita.",
      "Los ejercicios, grabados en el entrenamiento y vistos de nuevo en el partido.",
      "Os exercícios, filmados no treino e revistos depois no jogo.",
      "Les exercices, filmés à l’entraînement puis retrouvés en match.",
    ),
    identity: c(
      "What each position is asked to be, role by role.",
      "Che cosa si chiede a ogni ruolo, posizione per posizione.",
      "Lo que se le pide a cada puesto, posición por posición.",
      "O que se pede a cada posição, função a função.",
      "Ce qui est demandé à chaque poste, rôle par rôle.",
    ),
  },
};

export type CareerEntry = {
  club: string;
  place: Copy;
  role: Copy;
  /** ISO dates. No end date means he is still in the role. */
  start: string;
  end?: string;
  /**
   * How long he says he was there, when that differs from the dates.
   * Written with "about", because these are his figures, not a day count.
   */
  span?: Copy;
  note: Copy;
};

export const career = {
  kicker: c(
    "03 — Coaching path",
    "03 — Percorso in panchina",
    "03 — Trayectoria en el banquillo",
    "03 — Percurso como treinador",
    "03 — Parcours d’entraîneur",
  ),
  title: c("The path", "Il percorso", "El camino", "O percurso", "Le parcours"),
  intro: c(
    "Academy, youth sector, senior football abroad, then home to Naples.",
    "Academy, settore giovanile, prime squadre all’estero, poi il ritorno a Napoli.",
    "Academia, fútbol base, primeros equipos en el extranjero y, después, la vuelta a Nápoles.",
    "Academia, formação, equipas principais no estrangeiro e, depois, o regresso a Nápoles.",
    "Académie, secteur jeunes, équipes premières à l’étranger, puis le retour à Naples.",
  ),
  entries: [
    {
      club: "SSC Napoli Under-19",
      place: c("Naples, Italy", "Napoli, Italia", "Nápoles, Italia", "Nápoles, Itália", "Naples, Italie"),
      role: c("Head coach", "Allenatore", "Entrenador", "Treinador principal", "Entraîneur principal"),
      start: "2026-07-24",
      note: c(
        "Primavera 2, UEFA Youth League and Coppa Italia Primavera in 2026/27.",
        "Primavera 2, UEFA Youth League e Coppa Italia Primavera nel 2026/27.",
        "Primavera 2, UEFA Youth League y Coppa Italia Primavera en 2026/27.",
        "Primavera 2, UEFA Youth League e Coppa Italia Primavera em 2026/27.",
        "Primavera 2, UEFA Youth League et Coppa Italia Primavera en 2026/27.",
      ),
    },
    {
      club: "Las Vegas Lights FC",
      place: c("Las Vegas, USA", "Las Vegas, USA", "Las Vegas, EE. UU.", "Las Vegas, EUA", "Las Vegas, États-Unis"),
      role: c("Head coach", "Allenatore", "Entrenador", "Treinador principal", "Entraîneur principal"),
      start: "2025-01-09",
      end: "2025-06-10",
      span: c(
        "About 7 months",
        "Circa 7 mesi",
        "Unos 7 meses",
        "Cerca de 7 meses",
        "Environ 7 mois",
      ),
      note: c(
        "Senior head coach in the USL Championship.",
        "Allenatore della prima squadra in USL Championship.",
        "Entrenador del primer equipo en la USL Championship.",
        "Treinador da equipa principal na USL Championship.",
        "Entraîneur de l’équipe première en USL Championship.",
      ),
    },
    {
      club: "Miami FC",
      place: c("Miami, USA", "Miami, USA", "Miami, EE. UU.", "Miami, EUA", "Miami, États-Unis"),
      role: c("Head coach", "Allenatore", "Entrenador", "Treinador principal", "Entraîneur principal"),
      start: "2023-11-14",
      end: "2024-10-16",
      span: c(
        "About a year",
        "Circa un anno",
        "Alrededor de un año",
        "Cerca de um ano",
        "Environ un an",
      ),
      note: c(
        "First senior head-coach role, in the USL Championship.",
        "Primo incarico da allenatore di prima squadra, in USL Championship.",
        "Primera etapa como entrenador de un primer equipo, en la USL Championship.",
        "Primeira experiência como treinador de uma equipa principal, na USL Championship.",
        "Premier poste d’entraîneur d’une équipe première, en USL Championship.",
      ),
    },
    {
      club: "Potenza Calcio",
      place: c("Potenza, Italy", "Potenza, Italia", "Potenza, Italia", "Potenza, Itália", "Potenza, Italie"),
      role: c(
        "Head of youth sector · Under-19 head coach",
        "Responsabile del settore giovanile · Allenatore Under 19",
        "Responsable del fútbol base · Entrenador del Sub-19",
        "Responsável pela formação · Treinador dos Sub-19",
        "Responsable du secteur jeunes · Entraîneur des U19",
      ),
      start: "2022-07-09",
      end: "2023-06-02",
      span: c(
        "About a year",
        "Circa un anno",
        "Alrededor de un año",
        "Cerca de um ano",
        "Environ un an",
      ),
      note: c(
        "Led the club’s youth sector while coaching its Under-19s.",
        "Alla guida del settore giovanile del club e, insieme, dell’Under 19.",
        "Al frente del fútbol base del club y, a la vez, de su Sub-19.",
        "À frente da formação do clube e, ao mesmo tempo, dos seus Sub-19.",
        "À la tête du secteur jeunes du club tout en entraînant ses U19.",
      ),
    },
    {
      club: "Orlando City SC Academy",
      place: c("Orlando, USA", "Orlando, USA", "Orlando, EE. UU.", "Orlando, EUA", "Orlando, États-Unis"),
      role: c("Youth coach", "Allenatore giovanile", "Entrenador de formación", "Treinador de formação", "Entraîneur de jeunes"),
      start: "2020-01-24",
      end: "2022-06-30",
      span: c(
        "About a year and a half",
        "Circa un anno e mezzo",
        "Alrededor de un año y medio",
        "Cerca de um ano e meio",
        "Environ un an et demi",
      ),
      note: c(
        "Began the day after retiring as a player, at the club he had played for in MLS.",
        "Ha iniziato il giorno dopo il ritiro, nel club in cui aveva giocato in MLS.",
        "Empezó al día siguiente de retirarse, en el club en el que había jugado en la MLS.",
        "Começou no dia seguinte ao fim da carreira, no clube onde tinha jogado na MLS.",
        "A commencé le lendemain de sa retraite, dans le club où il avait joué en MLS.",
      ),
    },
  ] as CareerEntry[],
};

export const playing = {
  kicker: c(
    "04 — As a player",
    "04 — Da calciatore",
    "04 — Como jugador",
    "04 — Como jogador",
    "04 — Comme joueur",
  ),
  title: c(
    "Before the dugout",
    "Prima della panchina",
    "Antes del banquillo",
    "Antes do banco",
    "Avant le banc",
  ),
  intro: c(
    "Midfielder, professional from 2003 to 2020. Came through the youth systems of Juventus and Avellino.",
    "Centrocampista, professionista dal 2003 al 2020. Cresciuto nei settori giovanili di Juventus e Avellino.",
    "Centrocampista, profesional de 2003 a 2020. Formado en las canteras de la Juventus y el Avellino.",
    "Médio, profissional de 2003 a 2020. Formado nas escolas da Juventus e do Avellino.",
    "Milieu de terrain, professionnel de 2003 à 2020. Formé à la Juventus et à Avellino.",
  ),
  honours: [
    {
      figure: "15",
      label: c(
        "caps for Italy",
        "presenze in Nazionale",
        "partidos con Italia",
        "internacionalizações por Itália",
        "sélections avec l’Italie",
      ),
    },
    {
      figure: "2012",
      label: c(
        "European Championship runner-up",
        "Vicecampione d’Europa",
        "Subcampeón de Europa",
        "Vice-campeão da Europa",
        "Finaliste de l’Euro",
      ),
    },
    {
      figure: "2008",
      label: c(
        "Olympic Games with Italy",
        "Olimpiadi con l’Italia",
        "Juegos Olímpicos con Italia",
        "Jogos Olímpicos com a Itália",
        "Jeux olympiques avec l’Italie",
      ),
    },
    {
      figure: "2011–14",
      label: c(
        "Champions League with AC Milan",
        "Champions League con il Milan",
        "Champions League con el AC Milan",
        "Liga dos Campeões com o AC Milan",
        "Ligue des champions avec l’AC Milan",
      ),
    },
  ],
  clubsLabel: c("Clubs", "Squadre", "Clubes", "Clubes", "Clubs"),
  clubs: [
    { name: "Avellino", years: "2003–04" },
    { name: "Genoa", years: "2004–06" },
    { name: "Catanzaro", years: "2005" },
    { name: "Crotone", years: "2005" },
    { name: "Messina", years: "2006" },
    { name: "Piacenza", years: "2006–07" },
    { name: "Juventus", years: "2007–08" },
    { name: "Palermo", years: "2008–11" },
    { name: "AC Milan", years: "2011–16" },
    { name: "West Ham United", years: "2014" },
    { name: "Torino", years: "2014–15" },
    { name: "Parma", years: "2015" },
    { name: "Orlando City", years: "2016–17" },
    { name: "Benevento", years: "2018" },
  ],
};

export const contact = {
  kicker: c("05 — Contact", "05 — Contatti", "05 — Contacto", "05 — Contacto", "05 — Contact"),
  title: c(
    "Get in touch",
    "Per mettersi in contatto",
    "Para ponerse en contacto",
    "Para entrar em contacto",
    "Prendre contact",
  ),
  body: c(
    "For clubs, sporting directors and federations who want to talk football.",
    "Per club, direttori sportivi e federazioni che vogliono parlare di calcio.",
    "Para clubes, directores deportivos y federaciones que quieran hablar de fútbol.",
    "Para clubes, diretores desportivos e federações que queiram falar de futebol.",
    "Pour les clubs, directeurs sportifs et fédérations qui veulent parler football.",
  ),
  pending: c(
    "Contact details will be added here shortly.",
    "I recapiti saranno aggiunti qui a breve.",
    "Los datos de contacto se añadirán aquí en breve.",
    "Os contactos serão adicionados aqui em breve.",
    "Les coordonnées seront ajoutées ici prochainement.",
  ),
  emailLabel: c("Email", "Email", "Correo", "Email", "E-mail"),
  phoneLabel: c("Phone", "Telefono", "Teléfono", "Telefone", "Téléphone"),
  linkedinLabel: c("LinkedIn", "LinkedIn", "LinkedIn", "LinkedIn", "LinkedIn"),
  representationLabel: c(
    "Representation",
    "Procuratore",
    "Representación",
    "Representação",
    "Représentation",
  ),
};

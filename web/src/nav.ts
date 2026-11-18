// Navigazione con l'hash dell'indirizzo (#/search, #/card/en/sv03.5-006): funziona anche offline e nella Home.

export function go(path: string) {
  location.hash = `#/${path}`;
}

export function openCard(lang: string, id: string) {
  go(`card/${encodeURIComponent(lang)}/${encodeURIComponent(id)}`);
}

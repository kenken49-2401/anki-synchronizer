// Load nearby cards in their displayed order, including their hidden answers.
export function observeCardMedia(root, media, isCurrent, Observer = globalThis.IntersectionObserver) {
  if (!media.loadImage) return () => {};
  let active = true, running = false;
  const pending = new Set();
  const cards = [...root.querySelectorAll('.study-card')];
  const load = async (image) => {
    const id = image.dataset.mediaId;
    if (!id) return;
    image.nextElementSibling?.matches('[data-image-retry]') && image.nextElementSibling.remove();
    if (!image.dataset.originalAlt) image.dataset.originalAlt = image.alt || 'カードの図';
    image.alt = '画像を読み込み中…';
    try {
      const url = await media.loadImage(id);
      if (active && isCurrent() && image.isConnected) {
        image.src = url;
        image.alt = image.dataset.originalAlt;
        delete image.dataset.mediaId;
      }
    } catch {
      if (active && isCurrent() && image.isConnected) {
        image.alt = '画像を読み込めませんでした。';
        if (image.nextElementSibling?.matches('[data-image-retry]')) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'button subtle small';
        button.dataset.imageRetry = '';
        button.textContent = '画像を再読み込み';
        button.addEventListener('click', () => void load(image));
        image.after(button);
      }
    }
  };
  const drain = async () => {
    if (running) return;
    running = true;
    while (active && isCurrent() && pending.size) {
      const card = cards.find(item => pending.has(item));
      if (!card) break;
      pending.delete(card);
      for (const image of card.querySelectorAll('.card-question img[data-media-id], .answer-content img[data-media-id]')) {
        if (!active || !isCurrent() || !card.isConnected) break;
        await load(image);
      }
    }
    running = false;
  };
  let observer;
  if (Observer) {
    observer = new Observer(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) pending.add(entry.target);
        else pending.delete(entry.target);
      }
      void drain();
    }, {rootMargin: '500px'});
    cards.forEach(card => observer.observe(card));
  } else {
    cards.forEach(card => pending.add(card));
    void drain();
  }
  return () => { active = false; pending.clear(); observer?.disconnect(); };
}

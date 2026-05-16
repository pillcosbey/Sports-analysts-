// Footer year
document.getElementById('year').textContent = new Date().getFullYear();

// Mobile nav
const navToggle = document.getElementById('navToggle');
const navLinks = document.getElementById('navLinks');
navToggle.addEventListener('click', () => {
  const open = navLinks.classList.toggle('open');
  navToggle.setAttribute('aria-expanded', open);
});
navLinks.querySelectorAll('a').forEach((a) => {
  a.addEventListener('click', () => {
    navLinks.classList.remove('open');
    navToggle.setAttribute('aria-expanded', 'false');
  });
});

// ---------- Lightbox ----------
const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightboxImg');
const lightboxClose = document.getElementById('lightboxClose');
const lightboxPrev = document.getElementById('lightboxPrev');
const lightboxNext = document.getElementById('lightboxNext');

let galleryImages = [];
let currentIndex = 0;

function collectGallery() {
  galleryImages = Array.from(
    document.querySelectorAll('.gallery-item img')
  ).filter((img) => !img.classList.contains('missing'));
}

function openLightbox(index) {
  collectGallery();
  if (!galleryImages.length) return;
  currentIndex = index;
  showLightbox();
  lightbox.hidden = false;
  document.body.style.overflow = 'hidden';
}

function showLightbox() {
  const img = galleryImages[currentIndex];
  lightboxImg.src = img.src;
  lightboxImg.alt = img.alt;
}

function closeLightbox() {
  lightbox.hidden = true;
  document.body.style.overflow = '';
}

function step(dir) {
  currentIndex = (currentIndex + dir + galleryImages.length) % galleryImages.length;
  showLightbox();
}

document.querySelectorAll('.gallery-item').forEach((item) => {
  item.addEventListener('click', () => {
    const img = item.querySelector('img');
    if (img.classList.contains('missing')) return;
    collectGallery();
    const idx = galleryImages.indexOf(img);
    if (idx > -1) openLightbox(idx);
  });
});

lightboxClose.addEventListener('click', closeLightbox);
lightboxPrev.addEventListener('click', () => step(-1));
lightboxNext.addEventListener('click', () => step(1));
lightbox.addEventListener('click', (e) => {
  if (e.target === lightbox) closeLightbox();
});
document.addEventListener('keydown', (e) => {
  if (lightbox.hidden) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') step(-1);
  if (e.key === 'ArrowRight') step(1);
});

// ---------- Booking form ----------
const form = document.getElementById('bookingForm');
const checkin = document.getElementById('checkin');
const checkout = document.getElementById('checkout');
const formError = document.getElementById('formError');

const today = new Date().toISOString().split('T')[0];
checkin.min = today;
checkout.min = today;

checkin.addEventListener('change', () => {
  checkout.min = checkin.value || today;
  if (checkout.value && checkout.value <= checkin.value) checkout.value = '';
});

function showError(msg) {
  formError.textContent = msg;
  formError.hidden = false;
  formError.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

form.addEventListener('submit', (e) => {
  formError.hidden = true;

  if (checkin.value && checkout.value && checkout.value <= checkin.value) {
    e.preventDefault();
    showError('Your check-out date must be after your check-in date.');
    return;
  }

  // If the form endpoint has not been configured yet, fall back gracefully.
  if (form.action.includes('YOUR_FORM_ID')) {
    e.preventDefault();
    showError(
      'The booking form is not connected yet. To finish setup, create a free form at formspree.io and replace YOUR_FORM_ID in index.html with your form endpoint.'
    );
  }
});

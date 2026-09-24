'use strict';
const video = document.getElementById('fitness-video');
const wrap = document.getElementById('video-wrap');
const start = document.getElementById('start-video');
const play = document.getElementById('play-toggle');
const sound = document.getElementById('sound-toggle');
const seek = document.getElementById('seek');
const time = document.getElementById('time-label');
const message = document.getElementById('player-message');
const dialog = document.getElementById('study-dialog');
const formatTime = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
let previousFocus = null;

// No autoplay with sound: a deliberate user click reliably unlocks audio.
async function playWithSound() {
  video.muted = false;
  video.volume = 1;
  if (video.ended) video.currentTime = 0;
  try { await video.play(); message.textContent = ''; }
  catch (_) { message.textContent = 'Playback could not start. Press play again, or open this page in Chrome or Edge.'; }
  syncControls();
}
function syncControls() {
  play.textContent = video.paused ? '▶' : 'Ⅱ';
  play.setAttribute('aria-label', video.paused ? 'Play video' : 'Pause video');
  wrap.classList.toggle('playing', !video.paused || video.currentTime > 0);
  sound.textContent = video.muted ? 'ENABLE SOUND' : 'SOUND ON';
  sound.setAttribute('aria-label', video.muted ? 'Unmute sound' : 'Mute sound');
  sound.setAttribute('aria-pressed', String(video.muted));
}
start.addEventListener('click', playWithSound);
document.getElementById('watch-top').addEventListener('click', () => {
  wrap.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'center'});
  playWithSound();
});
play.addEventListener('click', async () => {
  if (video.paused) {
    try { await video.play(); } catch (_) { message.textContent = 'Press Play with sound to start the video.'; }
  } else video.pause();
});
video.addEventListener('click', () => { if (video.paused) video.play().catch(() => {}); else video.pause(); });
sound.addEventListener('click', () => { video.muted = !video.muted; syncControls(); });
seek.addEventListener('input', () => { video.currentTime = Number(seek.value); });
video.addEventListener('timeupdate', () => {
  seek.value = video.currentTime;
  time.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration || 17.47)}`;
});
video.addEventListener('loadedmetadata', () => { seek.max = video.duration; });
for (const event of ['play','pause','ended','volumechange']) video.addEventListener(event, syncControls);
video.addEventListener('ended', () => {
  start.querySelector('span:last-child').textContent = 'REPLAY WITH SOUND';
  wrap.classList.remove('playing');
});
video.addEventListener('error', () => { message.textContent = 'Video not found. Keep the landing/assets folder beside app.py as provided in the ZIP.'; });
document.getElementById('fullscreen').addEventListener('click', async () => {
  try {
    if (video.requestFullscreen) {video.controls = true; await video.requestFullscreen();}
    else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
  } catch (_) { message.textContent = 'Fullscreen is not available in this browser.'; }
});
document.addEventListener('fullscreenchange', () => {if (!document.fullscreenElement) video.controls = false;});
for (const button of document.querySelectorAll('[data-open-study]')) {
  button.addEventListener('click', () => { previousFocus = button; video.pause(); dialog.showModal(); });
}
function closeStudy() { dialog.close(); if (previousFocus) previousFocus.focus(); }
document.getElementById('close-study').addEventListener('click', closeStudy);
document.getElementById('back-home').addEventListener('click', closeStudy);
dialog.addEventListener('click', event => {if (event.target === dialog) {const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom) closeStudy();}});

// Minimal Streamlit component protocol: local media/fonts, no external JS/CDN.
function send(type, extra={}) {
  if (window.parent !== window) window.parent.postMessage({isStreamlitMessage:true,type,...extra}, '*');
}
let lastHeight=0;
function resize() {
  const height=Math.ceil(document.querySelector('.page').getBoundingClientRect().height)+2;
  if (height !== lastHeight) {lastHeight=height; send('streamlit:setFrameHeight',{height});}
}
window.addEventListener('message', async event => {
  if (event.source !== window.parent || event.data?.type !== 'streamlit:render') return;
  resize();
});
new ResizeObserver(resize).observe(document.querySelector('.page'));
window.addEventListener('load', resize);
document.fonts.ready.then(resize);
send('streamlit:componentReady',{apiVersion:1});
resize();

// Start automatically, keeping playback independent of sound permission.
async function autoStart() {
  video.loop = true;
  video.muted = false;
  try { await video.play(); }
  catch (_) {
    video.muted = true;
    try { await video.play(); }
    catch (_) { message.textContent = 'Autoplay is blocked by your browser. Use the play button below.'; }
  }
  syncControls();
}
autoStart();

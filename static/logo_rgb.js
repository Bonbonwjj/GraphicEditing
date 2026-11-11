(() => {
  const logo = document.querySelector('.rgbAxesLogo');
  if (!logo) return;

  logo.tabIndex = 0;
  logo.setAttribute('role', 'button');
  logo.setAttribute('aria-haspopup', 'dialog');
  logo.setAttribute('aria-expanded', 'false');
  logo.title = '点击调节 Logo 的 RGB 通道';

  const panel = document.createElement('section');
  panel.className = 'logoRgbPanel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Logo RGB 调色器');
  panel.innerHTML = `
    <div class="logoRgbHead"><strong>RGB 通道</strong><span class="logoRgbSwatch" aria-hidden="true"></span></div>
    <label class="rgbR"><b>R</b><input type="range" min="0" max="255" value="255"><output>255</output></label>
    <label class="rgbG"><b>G</b><input type="range" min="0" max="255" value="255"><output>255</output></label>
    <label class="rgbB"><b>B</b><input type="range" min="0" max="255" value="255"><output>255</output></label>
    <div class="logoRgbFoot"><small>实时预览</small><button type="button">复位</button></div>`;
  logo.closest('.brand').append(panel);

  const controls = [...panel.querySelectorAll('input[type="range"]')];
  const outputs = [...panel.querySelectorAll('output')];
  const swatch = panel.querySelector('.logoRgbSwatch');
  const targets = [
    [logo.querySelector('.channelR'), logo.querySelector('.redMini')],
    [logo.querySelector('.channelG'), logo.querySelector('.greenMini')],
    [logo.querySelector('.channelB'), logo.querySelector('.blueMini')],
  ];

  function render() {
    const [r, g, b] = controls.map(control => Number(control.value));
    const colors = [`rgb(${r},0,0)`, `rgb(0,${g},0)`, `rgb(0,0,${b})`];
    controls.forEach((control, index) => {
      outputs[index].value = control.value;
      targets[index].forEach(target => {
        if (!target) return;
        target.style.stroke = colors[index];
        target.style.filter = `drop-shadow(0 0 2px ${colors[index]})`;
      });
    });
    swatch.style.background = `rgb(${r},${g},${b})`;
  }

  function setOpen(open) {
    panel.hidden = !open;
    logo.setAttribute('aria-expanded', String(open));
    if (open) controls[0].focus();
  }

  logo.addEventListener('click', () => setOpen(panel.hidden));
  logo.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setOpen(panel.hidden);
    }
  });
  controls.forEach(control => control.addEventListener('input', render));
  panel.querySelector('button').addEventListener('click', () => {
    controls.forEach(control => { control.value = '255'; });
    render();
  });
  document.addEventListener('pointerdown', event => {
    if (!panel.hidden && !panel.contains(event.target) && !logo.contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) {
      setOpen(false);
      logo.focus();
    }
  });
  render();
})();

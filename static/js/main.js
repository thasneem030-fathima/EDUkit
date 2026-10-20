// EduKit Customizer Preview - 100% working
document.addEventListener('DOMContentLoaded', () => {
  const textInput = document.getElementById('text');
  const logoInput = document.getElementById('logo');
  const colourInput = document.getElementById('colour');
  const ptext = document.getElementById('ptext');
  const plogo = document.getElementById('plogo');
  const previewBox = document.getElementById('preview');

  if (textInput && ptext) {
    textInput.addEventListener('input', () => {
      ptext.textContent = textInput.value;
    });
  }

  if (logoInput && plogo) {
    logoInput.addEventListener('change', () => {
      const file = logoInput.files[0];
      if (file) {
        plogo.src = URL.createObjectURL(file);
        plogo.hidden = false;
        plogo.style.maxWidth = '140px';
        plogo.style.maxHeight = '140px';
        plogo.style.marginTop = '10px';
      }
    });
  }

  if (colourInput && previewBox) {
    colourInput.addEventListener('input', () => {
      previewBox.style.borderColor = colourInput.value;
      previewBox.style.background = colourInput.value + '15';
    });
  }
});
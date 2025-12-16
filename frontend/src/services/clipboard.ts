export async function copyTextToClipboard(text: string): Promise<void> {
  if (!text) {
    throw new Error('No text to copy');
  }

  // Try modern clipboard API first (works on most browsers including iOS 13.4+)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall through to legacy method
    }
  }

  // Legacy fallback for older iOS and other browsers
  const textArea = document.createElement('textarea');
  textArea.value = text;
  
  // Prevent zoom on iOS
  textArea.style.fontSize = '16px';
  
  // Make it invisible but still functional
  textArea.style.position = 'fixed';
  textArea.style.top = '50%';
  textArea.style.left = '50%';
  textArea.style.transform = 'translate(-50%, -50%)';
  textArea.style.opacity = '0';
  textArea.style.pointerEvents = 'none';
  textArea.setAttribute('readonly', '');
  
  document.body.appendChild(textArea);
  
  // iOS-specific selection handling
  const range = document.createRange();
  range.selectNodeContents(textArea);
  
  const selection = window.getSelection();
  if (selection) {
    selection.removeAllRanges();
    selection.addRange(range);
  }
  
  textArea.setSelectionRange(0, text.length);

  let successful = false;
  try {
    successful = document.execCommand('copy');
  } catch {
    successful = false;
  }
  
  document.body.removeChild(textArea);

  if (!successful) {
    // Last resort: show prompt for manual copy
    window.prompt('Copy this URL manually:', text);
  }
}

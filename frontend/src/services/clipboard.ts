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
  // Use an input element instead of textarea - works better on iOS
  const input = document.createElement('input');
  input.type = 'text';
  input.value = text;
  
  // Prevent zoom on iOS (font size must be >= 16px)
  input.style.fontSize = '16px';
  
  // Position it in the viewport but make it invisible
  input.style.position = 'fixed';
  input.style.top = '0';
  input.style.left = '0';
  input.style.width = '100%';
  input.style.height = '40px';
  input.style.opacity = '0';
  input.style.zIndex = '-1';
  input.setAttribute('readonly', '');
  // Prevent iOS keyboard from appearing
  input.setAttribute('inputmode', 'none');
  
  document.body.appendChild(input);
  
  // iOS requires focus and select in a specific way
  input.focus();
  input.select();
  
  // For iOS, also try setSelectionRange
  input.setSelectionRange(0, text.length);

  let successful = false;
  try {
    successful = document.execCommand('copy');
  } catch {
    successful = false;
  }
  
  // Blur before removing to prevent iOS keyboard flash
  input.blur();
  document.body.removeChild(input);

  if (!successful) {
    // Last resort: throw so caller knows it failed
    // The caller can then show a manual copy option
    throw new Error('Copy failed - please copy manually');
  }
}

// Opens ClipMaker in its own standalone window instead of an attached popup,
// so clicking elsewhere on the page doesn't close it mid-entry.

let winId = null;

chrome.action.onClicked.addListener(async (tab) => {
  // If the window is already open, just focus it.
  if (winId !== null) {
    try {
      await chrome.windows.get(winId);
      await chrome.windows.update(winId, { focused: true, drawAttention: true });
      return;
    } catch (e) {
      winId = null; // it was closed
    }
  }

  const url = tab && tab.url ? tab.url : "";
  const isYt = /^https?:\/\/((www\.|m\.|music\.)?youtube\.com\/|youtu\.be\/)/i.test(url);
  const page =
    chrome.runtime.getURL("popup.html") + (isYt ? "?u=" + encodeURIComponent(url) : "");

  const w = await chrome.windows.create({
    url: page,
    type: "popup",
    width: 400,
    height: 480,
    focused: true,
  });
  winId = w.id;
});

chrome.windows.onRemoved.addListener((id) => {
  if (id === winId) winId = null;
});

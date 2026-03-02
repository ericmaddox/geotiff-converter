(function () {
  var _initialized = false;
  var _fileInput = null;

  // Prevent the browser from opening dropped files anywhere on the page
  document.addEventListener("dragover", function (e) {
    e.preventDefault();
  });
  document.addEventListener("drop", function (e) {
    e.preventDefault();
  });

  function tryInit() {
    if (_initialized) return;
    var dropZone = document.getElementById("drop-zone");
    if (!dropZone) return;
    _initialized = true;
    console.log("[upload.js] drop-zone found, attaching listeners");

    // Create a hidden file input for click-to-browse
    _fileInput = document.createElement("input");
    _fileInput.type = "file";
    _fileInput.multiple = true;
    _fileInput.style.display = "none";
    _fileInput.accept =
      ".pdf,.docx,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.gif,.webp";
    document.body.appendChild(_fileInput);

    // Click to browse
    dropZone.addEventListener("click", function () {
      _fileInput.click();
    });

    _fileInput.addEventListener("change", function () {
      if (this.files.length > 0) uploadFiles(this.files);
      this.value = "";
    });

    // Drag visual feedback
    dropZone.addEventListener("dragenter", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("drag-over");
    });

    dropZone.addEventListener("dragover", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("drag-over");
    });

    dropZone.addEventListener("dragleave", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("drag-over");
    });

    // Drop handler
    dropZone.addEventListener("drop", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("drag-over");
      if (e.dataTransfer && e.dataTransfer.files.length > 0) {
        uploadFiles(e.dataTransfer.files);
      }
    });
  }

  function uploadFiles(files) {
    var dropZone = document.getElementById("drop-zone");
    var sessionId = dropZone.getAttribute("data-session");

    var formData = new FormData();
    formData.append("session_id", sessionId);
    for (var i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }

    console.log("[upload.js] uploading " + files.length + " file(s)");
    dropZone.classList.add("uploading");

    fetch("/api/upload", { method: "POST", body: formData })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        console.log("[upload.js] upload complete:", data);
        dropZone.classList.remove("uploading");
      })
      .catch(function (err) {
        console.error("[upload.js] upload failed:", err);
        dropZone.classList.remove("uploading");
      });
  }

  // Dash loads layout async — poll until the drop zone element exists
  tryInit();
  var check = setInterval(function () {
    tryInit();
    if (_initialized) clearInterval(check);
  }, 200);
})();

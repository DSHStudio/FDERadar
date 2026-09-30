"use strict";

function bindFormSubmission(form, submit, { draftKey, path, prepare, successMessage, onSuccess }) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = prepare();
    if (body === null) return;
    submit.disabled = true;
    try {
      await api(path, body);
      app.formDrafts.delete(draftKey);
      if (onSuccess) onSuccess();
      message(successMessage);
      submit.blur();
      await refresh();
    } catch (error) {
      message(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
}

function bindFormDraft(form, key, controls) {
  const draft = app.formDrafts.get(key);
  if (draft)
    controls.forEach((control, index) => {
      if (draft[index] !== undefined) control.value = draft[index];
    });
  const remember = () =>
    app.formDrafts.set(
      key,
      controls.map((control) => control.value),
    );
  form.addEventListener("input", remember);
  form.addEventListener("change", remember);
}

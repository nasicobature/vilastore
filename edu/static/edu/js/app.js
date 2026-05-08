(function () {
  const ready = () => {
    if (window.lucide) {
      window.lucide.createIcons();
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ready);
  } else {
    ready();
  }

  const cards = document.querySelectorAll('.card.selectable');
  cards.forEach((card) => {
    card.addEventListener('click', () => {
      const institution = card.getAttribute('data-institution');
      if (institution) {
        window.location.href = `/edu/${institution}/login/`;
      }
    });
  });

  const wizardForms = document.querySelectorAll('[data-registration-wizard]');
  wizardForms.forEach((form) => {
    const panels = Array.from(form.querySelectorAll('[data-wizard-panel]'));
    const container = form.closest('.registration-card');
    const indicators = container ? Array.from(container.querySelectorAll('[data-step-indicator]')) : [];
    const prevButton = form.querySelector('[data-wizard-prev]');
    const nextButton = form.querySelector('[data-wizard-next]');
    const submitButton = form.querySelector('[data-wizard-submit]');
    const errorBox = form.querySelector('[data-wizard-error]');
    const reviewOutput = form.querySelector('[data-review-output]');
    let currentStep = 0;

    const showError = (message) => {
      if (!errorBox) return;
      errorBox.textContent = message;
      errorBox.hidden = !message;
    };

    const fieldLabel = (field) => {
      const label = field.closest('label');
      if (!label) return field.name || 'Required field';
      const clone = label.cloneNode(true);
      clone.querySelectorAll('input, select, small, span, i, em').forEach((node) => node.remove());
      return clone.textContent.replace('*', '').trim() || field.name || 'Required field';
    };

    const validatePanel = (panel) => {
      const requiredFields = Array.from(panel.querySelectorAll('[required]'));
      for (const field of requiredFields) {
        if (field.type === 'file' && !field.files.length) {
          showError(`${fieldLabel(field)} is required.`);
          field.focus({ preventScroll: true });
          return false;
        }
        if (field.type !== 'file' && !field.value.trim()) {
          showError(`${fieldLabel(field)} is required.`);
          field.focus({ preventScroll: true });
          return false;
        }
      }

      const requiredGroups = Array.from(new Set(
        Array.from(panel.querySelectorAll('[data-required-group]')).map((field) => field.dataset.requiredGroup)
      ));
      for (const group of requiredGroups) {
        const hasFile = Array.from(panel.querySelectorAll(`[data-required-group="${group}"]`)).some((field) => field.files.length);
        if (!hasFile) {
          showError(group === 'license'
            ? 'Upload either Ministry Approval or School Operating License.'
            : 'Upload either Utility Bill or Proof of Address.');
          return false;
        }
      }

      showError('');
      return true;
    };

    const buildReview = () => {
      if (!reviewOutput) return;
      const fields = Array.from(form.querySelectorAll('[data-review-label]'));
      reviewOutput.innerHTML = fields.map((field) => {
        let value = 'Not provided';
        if (field.type === 'file') {
          value = field.files.length ? field.files[0].name : 'Not uploaded';
        } else if (field.tagName === 'SELECT') {
          value = field.options[field.selectedIndex] ? field.options[field.selectedIndex].text : field.value;
        } else if (field.value.trim()) {
          value = field.value.trim();
        }
        return `<div class="review-item"><span>${field.dataset.reviewLabel}</span><strong>${value}</strong></div>`;
      }).join('');
      if (window.lucide) {
        window.lucide.createIcons();
      }
    };

    const setStep = (step) => {
      currentStep = Math.max(0, Math.min(step, panels.length - 1));
      panels.forEach((panel, index) => {
        panel.classList.toggle('is-active', index === currentStep);
      });
      indicators.forEach((indicator, index) => {
        indicator.classList.toggle('is-active', index === currentStep);
        indicator.classList.toggle('is-complete', index < currentStep);
      });
      if (prevButton) {
        prevButton.hidden = currentStep === 0;
      }
      if (nextButton) {
        nextButton.hidden = currentStep === panels.length - 1;
      }
      if (submitButton) {
        submitButton.hidden = currentStep !== panels.length - 1;
      }
      showError('');
      if (currentStep === panels.length - 1) {
        buildReview();
      }
      form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    if (prevButton) {
      prevButton.addEventListener('click', () => setStep(currentStep - 1));
    }
    if (nextButton) {
      nextButton.addEventListener('click', () => {
        if (validatePanel(panels[currentStep])) {
          setStep(currentStep + 1);
        }
      });
    }
    form.addEventListener('submit', (event) => {
      for (let index = 0; index < panels.length; index += 1) {
        if (!validatePanel(panels[index])) {
          event.preventDefault();
          setStep(index);
          validatePanel(panels[index]);
          return;
        }
      }
    });

    setStep(0);
  });

  const onlinePaymentForms = document.querySelectorAll('[data-edu-online-payment]');
  onlinePaymentForms.forEach((form) => {
    const feeSelect = form.querySelector('select[name="fee"]');
    const studentSelect = form.querySelector('select[name="student"]');
    const amountInput = form.querySelector('input[name="amount"]');
    const referenceInput = form.querySelector('[data-payment-reference]');
    const publicKeyInput = form.querySelector('input[name="public_key"]');
    const payButton = form.querySelector('[data-pay-online]');

    if (feeSelect && amountInput) {
      feeSelect.addEventListener('change', () => {
        const option = feeSelect.options[feeSelect.selectedIndex];
        if (option && option.dataset.amount) {
          amountInput.value = option.dataset.amount;
        }
      });
    }

    if (payButton) {
      payButton.addEventListener('click', () => {
        if (!feeSelect.value || !studentSelect.value || !amountInput.value) {
          alert('Select fee, student, and amount before payment.');
          return;
        }
        if (!window.FlutterwaveCheckout) {
          alert('Flutterwave checkout is not available. Check your internet connection and try again.');
          return;
        }

        const studentOption = studentSelect.options[studentSelect.selectedIndex];
        const feeOption = feeSelect.options[feeSelect.selectedIndex];
        const publicKey = publicKeyInput ? publicKeyInput.value : '';
        const amount = Number(amountInput.value || 0);
        if (!publicKey || amount <= 0) {
          alert('Payment key or amount is missing.');
          return;
        }

        FlutterwaveCheckout({
          public_key: publicKey,
          tx_ref: `EDU-${Date.now()}`,
          amount: amount,
          currency: 'NGN',
          payment_options: 'card,banktransfer,ussd',
          customer: {
            email: studentOption.dataset.email || 'student@edupayment.local',
            name: studentOption.dataset.name || studentOption.textContent.trim(),
          },
          customizations: {
            title: 'EduPortal School Fees',
            description: feeOption.textContent.trim(),
          },
          callback: function (response) {
            referenceInput.value = response.transaction_id || response.tx_ref || '';
            form.submit();
          },
          onclose: function () {},
        });
      });
    }
  });

  const navLinks = document.querySelectorAll('.nav-item');
  const activeClasses = ['bg-sidebar-accent', 'text-sidebar-accent-foreground', 'font-medium'];
  const inactiveClasses = ['text-sidebar-foreground/70'];

  const setActive = (hash) => {
    navLinks.forEach((link) => {
      const href = link.getAttribute('href');
      const isActive = href === hash;
      activeClasses.forEach((cls) => link.classList.toggle(cls, isActive));
      inactiveClasses.forEach((cls) => link.classList.toggle(cls, !isActive));
    });
  };

  navLinks.forEach((link) => {
    link.addEventListener('click', (event) => {
      const href = link.getAttribute('href');
      if (href && href.startsWith('#')) {
        event.preventDefault();
        setActive(href);
        const target = document.querySelector(href);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth' });
        }
        history.replaceState(null, '', href);
      }
    });
  });

  if (window.location.hash) {
    setActive(window.location.hash);
  }

  const classSubjectMapEl = document.getElementById('class-subject-map');
  const classSelect = document.getElementById('class-subject-class');
  const subjectInputs = Array.from(document.querySelectorAll('.subject-input'));

  if (classSubjectMapEl && classSelect && subjectInputs.length) {
    const classSubjectMap = JSON.parse(classSubjectMapEl.textContent || '{}');
    const syncSubjects = () => {
      const selectedClass = classSelect.value;
      const assigned = (classSubjectMap && classSubjectMap[selectedClass]) || [];
      const assignedSet = new Set(assigned.map(String));
      subjectInputs.forEach((input) => {
        input.checked = assignedSet.has(input.value);
      });
    };

    classSelect.addEventListener('change', syncSubjects);
    syncSubjects();
  }

  const teacherSubjectMapEl = document.getElementById('teacher-subject-map');
  const teacherResultsMapEl = document.getElementById('teacher-results-map');
  const teacherClassSelect = document.getElementById('teacher-score-class');
  const teacherSubjectSelect = document.getElementById('teacher-score-subject');
  const teacherFetchButton = document.getElementById('teacher-score-fetch');
  const teacherEmptyRow = document.getElementById('teacher-score-empty');
  const teacherSubmitClassSelect = document.getElementById('teacher-submit-class');
  const teacherSubmitSubjectSelect = document.getElementById('teacher-submit-subject');
  const scoreRows = Array.from(document.querySelectorAll('.teacher-score-row'));

  if (teacherSubjectMapEl) {
    const subjectMap = JSON.parse(teacherSubjectMapEl.textContent || '{}');
    const resultsMap = teacherResultsMapEl ? JSON.parse(teacherResultsMapEl.textContent || '{}') : {};
    const searchInput = document.getElementById('teacher-score-search');

    const populateSubjects = (classSelectEl, subjectSelectEl) => {
      if (!classSelectEl || !subjectSelectEl) return;
      const classId = classSelectEl.value;
      const subjects = subjectMap[classId] || [];
      subjectSelectEl.innerHTML = '<option value="">Select Subject</option>';
      subjects.forEach((subject) => {
        const option = document.createElement('option');
        option.value = subject.id;
        option.textContent = subject.name;
        subjectSelectEl.appendChild(option);
      });
      if (!subjects.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No subjects assigned';
        option.disabled = true;
        subjectSelectEl.appendChild(option);
      }
    };

    let hasFetched = false;

    const setEmptyMessage = (message) => {
      if (!teacherEmptyRow) return;
      if (message) {
        teacherEmptyRow.style.display = '';
        const cell = teacherEmptyRow.querySelector('td');
        if (cell) {
          cell.textContent = message;
        }
      } else {
        teacherEmptyRow.style.display = 'none';
      }
    };

    const resetRows = () => {
      scoreRows.forEach((row) => {
        row.style.display = 'none';
        const studentInput = row.querySelector('input[name="students"]');
        if (!studentInput) return;
        const studentId = studentInput.value;
        ['test1', 'test2', 'assignment', 'exam'].forEach((field) => {
          const input = row.querySelector(`input[name="${field}_${studentId}"]`);
          if (input) {
            input.value = '';
          }
        });
        const statusEl = row.querySelector('.teacher-score-status');
        if (statusEl) {
          statusEl.textContent = 'Not saved';
          statusEl.classList.remove('bg-secondary/10', 'text-secondary');
          statusEl.classList.add('bg-muted', 'text-muted-foreground');
        }
      });
    };

    const filterStudents = () => {
      if (!teacherClassSelect) return;
      const classId = teacherClassSelect.value;
      const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
      let visibleCount = 0;
      scoreRows.forEach((row) => {
        const matchesClass = !classId || row.getAttribute('data-class') === classId;
        const studentId = (row.getAttribute('data-student-id') || '').toLowerCase();
        const matchesSearch = !query || studentId.includes(query);
        const show = matchesClass && matchesSearch;
        row.style.display = show ? '' : 'none';
        if (show) {
          visibleCount += 1;
        }
      });
      if (visibleCount === 0) {
        setEmptyMessage('No students found for this class/search.');
      } else {
        setEmptyMessage('');
      }
    };

    const applyExistingScores = () => {
      if (!teacherClassSelect || !teacherSubjectSelect) return;
      const subjectId = teacherSubjectSelect.value;
      scoreRows.forEach((row) => {
        if (row.style.display === 'none') {
          return;
        }
        const studentInput = row.querySelector('input[name="students"]');
        if (!studentInput) return;
        const studentId = studentInput.value;
        const key = `${studentId}-${subjectId}`;
        const scores = resultsMap[key];
        const statusEl = row.querySelector('.teacher-score-status');
        if (!scores) {
          ['test1', 'test2', 'assignment', 'exam'].forEach((field) => {
            const input = row.querySelector(`input[name="${field}_${studentId}"]`);
            if (input) {
              input.value = '';
            }
          });
          if (statusEl) {
            statusEl.textContent = 'Not saved';
            statusEl.classList.remove('bg-secondary/10', 'text-secondary');
            statusEl.classList.add('bg-muted', 'text-muted-foreground');
          }
          return;
        }
        row.querySelector(`input[name="test1_${studentId}"]`).value = scores.test1 ?? '';
        row.querySelector(`input[name="test2_${studentId}"]`).value = scores.test2 ?? '';
        row.querySelector(`input[name="assignment_${studentId}"]`).value = scores.assignment ?? '';
        row.querySelector(`input[name="exam_${studentId}"]`).value = scores.exam ?? '';
        if (statusEl) {
          statusEl.textContent = 'Saved';
          statusEl.classList.remove('bg-muted', 'text-muted-foreground');
          statusEl.classList.add('bg-secondary/10', 'text-secondary');
        }
      });
    };

    if (teacherClassSelect && teacherSubjectSelect) {
      teacherClassSelect.addEventListener('change', () => {
        populateSubjects(teacherClassSelect, teacherSubjectSelect);
        hasFetched = false;
        resetRows();
        setEmptyMessage('Select class and subject, then click Fetch Students.');
      });
      teacherSubjectSelect.addEventListener('change', () => {
        if (!hasFetched) return;
        applyExistingScores();
      });
      populateSubjects(teacherClassSelect, teacherSubjectSelect);
      resetRows();
      setEmptyMessage('Select class and subject, then click Fetch Students.');
    }

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        if (!hasFetched) return;
        filterStudents();
        applyExistingScores();
      });
    }

    if (teacherFetchButton) {
      teacherFetchButton.addEventListener('click', () => {
        if (!teacherClassSelect || !teacherSubjectSelect) return;
        if (!teacherClassSelect.value || !teacherSubjectSelect.value) {
          setEmptyMessage('Select class and subject before fetching students.');
          return;
        }
        hasFetched = true;
        filterStudents();
        applyExistingScores();
      });
    }

    if (teacherSubmitClassSelect && teacherSubmitSubjectSelect) {
      teacherSubmitClassSelect.addEventListener('change', () => {
        populateSubjects(teacherSubmitClassSelect, teacherSubmitSubjectSelect);
      });
      populateSubjects(teacherSubmitClassSelect, teacherSubmitSubjectSelect);
    }
  }
})();

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
        window.location.href = `/${institution}/login/`;
      }
    });
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

document.addEventListener('DOMContentLoaded', () => {
    const generateBtn = document.getElementById('generate-btn');
    const topicInput = document.getElementById('topic');
    const ctxInput = document.getElementById('ctx');
    const numStylesInput = document.getElementById('num_styles');

    const displayTopic = document.getElementById('display-topic');
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');

    const welcomeState = document.getElementById('welcome-state');
    const resultsArea = document.getElementById('results-area');
    const comparisonBody = document.getElementById('comparison-body');
    const resultsGrid = document.getElementById('results-grid');

    generateBtn.addEventListener('click', async () => {
        const topic = topicInput.value.trim();
        const ctx = ctxInput.value.trim();
        const num_styles = parseInt(numStylesInput.value);

        if (!topic) {
            alert('Please enter a topic.');
            return;
        }

        // UI Transition
        displayTopic.textContent = topic;
        welcomeState.classList.add('hidden');
        resultsArea.classList.add('hidden');
        statusIndicator.classList.remove('hidden');
        generateBtn.disabled = true;

        // Progress Tracking
        const steps = [
            "Grounding facts via Google Search...",
            "Contextualizing narrative boundaries...",
            "Art Director is brainstorming styles...",
            "Orchestrating parallel grid generation...",
            "Finalizing visual storyboards..."
        ];

        let stepIdx = 0;
        statusText.textContent = steps[0];
        const progressInterval = setInterval(() => {
            if (stepIdx < steps.length - 1) {
                stepIdx++;
                statusText.textContent = steps[stepIdx];
            }
        }, 4000);

        try {
            const response = await fetch('/api/moodboard', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    topic,
                    ctx: ctx || undefined,
                    num_styles
                }),
            });

            clearInterval(progressInterval);

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Generation failed');
            }

            const data = await response.json();
            renderDashboard(data.moodboard);

            resultsArea.classList.remove('hidden');
            statusIndicator.classList.add('hidden');
        } catch (error) {
            clearInterval(progressInterval);
            console.error('Error:', error);
            statusText.textContent = `Error: ${error.message}`;
            statusIndicator.style.background = '#ff0033';
            generateBtn.disabled = false;
        } finally {
            generateBtn.disabled = false;
        }
    });

    function renderDashboard(moodboard) {
        // Clear previous results
        comparisonBody.innerHTML = '';
        resultsGrid.innerHTML = '';

        if (!moodboard || moodboard.length === 0) {
            welcomeState.classList.remove('hidden');
            welcomeState.innerHTML = `<h3>No variations found</h3><p>Try adjusting your topic or context.</p>`;
            return;
        }

        moodboard.forEach(style => {
            // 1. Add to Comparison Table
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><span class="style-label">${style.style_name}</span></td>
                <td><p class="reasoning-text">${style.reasoning}</p></td>
                <td><img src="${style.grid_url}" class="table-img" alt="Preview"></td>
            `;
            comparisonBody.appendChild(row);

            // 2. Add to Detail Grid
            const card = document.createElement('div');
            card.className = 'style-card';
            card.innerHTML = `
                <div class="card-header">
                    <h4>${style.style_name}</h4>
                </div>
                <div class="card-img-container">
                    <img src="${style.grid_url}" alt="${style.style_name}" loading="lazy">
                </div>
                <div class="card-content">
                    <p class="card-reasoning">${style.reasoning}</p>
                </div>
            `;
            resultsGrid.appendChild(card);
        });
    }
});

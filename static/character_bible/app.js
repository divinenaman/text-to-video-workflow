document.addEventListener('DOMContentLoaded', () => {
    const generateBtn = document.getElementById('generate-btn');
    const storyInput = document.getElementById('story');
    const styleUrlsInput = document.getElementById('style_urls');

    const displayTopic = document.getElementById('display-topic');
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');

    const welcomeState = document.getElementById('welcome-state');
    const resultsArea = document.getElementById('results-area');
    const comparisonBody = document.getElementById('comparison-body');
    const resultsGrid = document.getElementById('results-grid');

    generateBtn.addEventListener('click', async () => {
        const story = storyInput.value.trim();
        const style_url = styleUrlsInput.value.trim();

        if (!story) {
            alert('Please enter a script/story.');
            return;
        }

        // UI Transition
        displayTopic.textContent = 'Casting Session';
        welcomeState.classList.add('hidden');
        resultsArea.classList.add('hidden');
        statusIndicator.classList.remove('hidden');
        generateBtn.disabled = true;

        // Progress Tracking
        const steps = [
            "Extracting characters...",
            "Building distinct visual profiles...",
            "Searching for references...",
            "Drafting character models...",
            "Finalizing Visual Bible..."
        ];

        let stepIdx = 0;
        statusText.textContent = steps[0];
        const progressInterval = setInterval(() => {
            if (stepIdx < steps.length - 1) {
                stepIdx++;
                statusText.textContent = steps[stepIdx];
            }
        }, 8000); // 8 seconds per step, roughly

        try {
            const bodyPayload = {
                story,
                style_urls: style_url ? [style_url] : []
            };

            const response = await fetch('/api/character_bible', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(bodyPayload),
            });

            clearInterval(progressInterval);

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Generation failed');
            }

            const data = await response.json();
            renderDashboard(data.characters);

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

    function renderDashboard(characters) {
        // Clear previous results
        comparisonBody.innerHTML = '';
        resultsGrid.innerHTML = '';

        if (!characters || characters.length === 0) {
            welcomeState.classList.remove('hidden');
            welcomeState.innerHTML = `<h3>No characters found</h3><p>Could not extract any characters from the text.</p>`;
            return;
        }

        characters.forEach(charInfo => {
            const characterUrl = (charInfo.urls && charInfo.urls.length > 0) ? charInfo.urls[0] : (charInfo.url || '');

            // 1. Add to Comparison Table
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><span class="style-label">${charInfo.name}</span></td>
                <td><p class="reasoning-text">${charInfo.description}</p></td>
                <td><img src="${characterUrl}" class="table-img" alt="Preview"></td>
            `;
            comparisonBody.appendChild(row);

            // 2. Add to Detail Grid
            const card = document.createElement('div');
            card.className = 'style-card';
            card.innerHTML = `
                <div class="card-header">
                    <h4>${charInfo.name}</h4>
                </div>
                <div class="card-img-container">
                    <img src="${characterUrl}" alt="${charInfo.name}" loading="lazy">
                </div>
                <div class="card-content">
                    <p class="card-reasoning">${charInfo.description}</p>
                </div>
            `;
            resultsGrid.appendChild(card);
        });
    }
});

/**
 * Timeline initialization and interactivity for ATNI-ResIST.
 *
 * Uses vis-timeline library to display resolutions chronologically.
 * Integrates with HTMX for loading resolution details.
 */
(function() {
    'use strict';

    // Get filter params from current URL
    const params = new URLSearchParams(window.location.search);

    // Container element
    const container = document.getElementById('timeline');
    const detailPane = document.getElementById('detail-pane');

    if (!container) {
        console.error('Timeline container not found');
        return;
    }

    // Show loading state
    container.innerHTML = '<p style="padding: 2rem; text-align: center;">Loading timeline data...</p>';

    // Fetch timeline data from API
    fetch('/api/timeline?' + params.toString())
        .then(function(response) {
            if (!response.ok) {
                throw new Error('Failed to load timeline data');
            }
            return response.json();
        })
        .then(function(data) {
            // Clear loading message
            container.innerHTML = '';

            if (data.items.length === 0) {
                container.innerHTML = '<p style="padding: 2rem; text-align: center;">No resolutions found matching the current filters.</p>';
                return;
            }

            // Create DataSet for vis-timeline
            const items = new vis.DataSet(data.items);

            // Timeline options
            const options = {
                start: data.start,
                end: data.end,
                zoomable: true,
                selectable: true,
                showCurrentTime: false,
                orientation: 'top',
                margin: {
                    item: 10
                },
                tooltip: {
                    followMouse: true,
                    overflowMethod: 'cap'
                },
                // Limit zoom range for usability
                zoomMin: 1000 * 60 * 60 * 24 * 30,  // 1 month minimum
                zoomMax: 1000 * 60 * 60 * 24 * 365 * 50,  // 50 years maximum
            };

            // Create timeline
            const timeline = new vis.Timeline(container, items, options);

            // Handle selection - load resolution detail via HTMX
            timeline.on('select', function(props) {
                if (props.items.length > 0) {
                    const id = props.items[0];

                    // Use HTMX to load resolution detail into the detail pane
                    // Adding HX-Request header to get appropriate response
                    htmx.ajax('GET', '/resolution/' + id, {
                        target: '#detail-pane',
                        swap: 'innerHTML',
                        headers: {
                            'HX-Request': 'true'
                        }
                    });
                }
            });

            // Handle double-click to navigate to full resolution page
            timeline.on('doubleClick', function(props) {
                if (props.item) {
                    window.location.href = '/resolution/' + props.item;
                }
            });

            // Fit timeline to show all items
            timeline.fit();
        })
        .catch(function(error) {
            console.error('Timeline error:', error);
            container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--pico-del-color);">Error loading timeline: ' + error.message + '</p>';
        });
})();

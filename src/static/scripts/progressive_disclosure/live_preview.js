/**
 * Weather live-preview and preview lightbox behavior.
 */
(function () {
    'use strict';

    const root = window.InkyPiProgressiveDisclosure || { mixins: {} };
    root.mixins = root.mixins || {};
    const escapeHtml = (value) => root.escapeHtml(value);

    root.mixins.livePreview = {
        initLivePreview() {
            const pluginId = document.querySelector('input[name="plugin_id"]')?.value;
            if (pluginId !== 'weather') return;

            const previewImage = document.getElementById('previewImage');
            const instancePreviewImage = document.getElementById('instancePreviewImage');

            if (!previewImage && !instancePreviewImage) return;

            const previewOverlay = document.createElement('div');
            previewOverlay.className = 'live-preview-overlay';
            previewOverlay.style.display = 'none';
            previewOverlay.innerHTML = `
                <div class="live-preview-header">
                    <span>Live Preview</span>
                    <button type="button" class="preview-close">×</button>
                </div>
                <div class="live-preview-content">
                    <div class="preview-section">
                        <h4>Current</h4>
                        <div class="preview-current"></div>
                    </div>
                    <div class="preview-section">
                        <h4>With Changes</h4>
                        <div class="preview-modified"></div>
                    </div>
                </div>
            `;

            document.body.appendChild(previewOverlay);

            const weatherInputs = document.querySelectorAll(`
                select[name="weatherIconPack"],
                select[name="moonIconPack"],
                select[name="layoutStyle"],
                select[name="forecastDays"],
                input[name="displayForecast"],
                input[name="displayGraph"],
                input[name="displayRefreshTime"],
                input[name="displayMetrics"],
                input[name="displayRain"],
                input[name="moonPhase"],
                select[name="weatherTimeZone"],
                select[name="titleSelection"],
                input[name="customTitle"]
            `.replace(/\s+/g, ''));

            let previewTimeout;
            const showLivePreview = () => {
                clearTimeout(previewTimeout);
                previewTimeout = setTimeout(() => {
                    this.updateLivePreview(previewOverlay);
                }, 1000);
            };

            weatherInputs.forEach((input) => {
                if (input) {
                    input.addEventListener('input', showLivePreview);
                    input.addEventListener('change', showLivePreview);
                }
            });

            document.addEventListener('click', (e) => {
                const target = e.target;
                if (target instanceof Element && target.matches('.button-group button[data-value]')) {
                    setTimeout(showLivePreview, 100);
                }
            });

            previewOverlay.querySelector('.preview-close').addEventListener('click', () => {
                previewOverlay.style.display = 'none';
            });

            document.addEventListener('settingsModeChanged', (e) => {
                if (e.detail.mode === 'advanced') {
                    setTimeout(() => this.updateLivePreview(previewOverlay), 100);
                }
            });
        },

        async updateLivePreview(overlay) {
            const previewImage = document.getElementById('previewImage');
            if (!previewImage || !previewImage.src) return;

            const currentPreview = overlay.querySelector('.preview-current');
            const modifiedPreview = overlay.querySelector('.preview-modified');

            currentPreview.innerHTML = '<div class="preview-loading">Loading current...</div>';
            modifiedPreview.innerHTML = '<div class="preview-loading">Generating preview...</div>';

            try {
                const currentImg = this.createPreviewImage(previewImage.src, 'Current Display');
                currentPreview.innerHTML = '';
                currentPreview.appendChild(currentImg);

                const changesSummary = this.detectFormChanges();

                if (changesSummary.hasIconPackChanges) {
                    const modifiedImageSrc = await this.generateIconPackPreview();
                    if (modifiedImageSrc) {
                        const modifiedImg = this.createPreviewImage(
                            modifiedImageSrc,
                            'Icon Pack Comparison'
                        );
                        modifiedPreview.innerHTML = '';
                        modifiedPreview.appendChild(modifiedImg);
                    } else {
                        this.showChangesSummary(modifiedPreview, changesSummary);
                    }
                } else {
                    this.showChangesSummary(modifiedPreview, changesSummary);
                }
            } catch (error) {
                console.warn('Live preview generation failed:', error);
                const changesSummary = this.detectFormChanges();
                this.showChangesSummary(modifiedPreview, changesSummary);
            }

            overlay.style.display = 'block';
            overlay.style.opacity = '0';
            requestAnimationFrame(() => {
                overlay.style.opacity = '1';
            });
        },

        detectFormChanges() {
            const form = document.getElementById('settingsForm');
            if (!form) return { hasChanges: false };

            const formData = new FormData(form);
            const changes = {
                hasChanges: false,
                hasIconPackChanges: false,
                changedSettings: [],
            };

            const weatherIconPack = formData.get('weatherIconPack');
            const moonIconPack = formData.get('moonIconPack');
            if (weatherIconPack && weatherIconPack !== 'current') {
                changes.hasIconPackChanges = true;
                changes.changedSettings.push(`Weather Icons: ${weatherIconPack}`);
            }
            if (moonIconPack && moonIconPack !== 'current') {
                changes.hasIconPackChanges = true;
                changes.changedSettings.push(`Moon Icons: ${moonIconPack}`);
            }

            const layoutStyle = formData.get('layoutStyle');
            if (layoutStyle && layoutStyle !== 'classic') {
                changes.changedSettings.push(`Layout: ${layoutStyle}`);
            }

            const forecastDays = formData.get('forecastDays');
            if (forecastDays && forecastDays !== '5') {
                changes.changedSettings.push(`Forecast: ${forecastDays} days`);
            }

            const displayForecast = formData.get('displayForecast');
            if (displayForecast === 'false' || !displayForecast) {
                changes.changedSettings.push('Forecast: Hidden');
            }

            const displayGraph = formData.get('displayGraph');
            if (displayGraph === 'false' || !displayGraph) {
                changes.changedSettings.push('Graph: Hidden');
            }

            const titleSelection = formData.get('titleSelection');
            const customTitle = formData.get('customTitle');
            if (titleSelection === 'custom' && customTitle) {
                changes.changedSettings.push(`Title: "${customTitle}"`);
            }

            changes.hasChanges = changes.changedSettings.length > 0;
            return changes;
        },

        showChangesSummary(container, changesSummary) {
            if (!changesSummary.hasChanges) {
                container.innerHTML = `
                    <div class="preview-placeholder">
                        <div class="preview-icon">📋</div>
                        <div class="preview-text">No changes detected</div>
                        <div class="preview-subtext">Modify settings to see preview</div>
                    </div>
                `;
                return;
            }

            const changesHtml = changesSummary.changedSettings
                .map((change) => `<div class="change-item">• ${escapeHtml(change)}</div>`)
                .join('');

            container.innerHTML = `
                <div class="preview-placeholder">
                    <div class="preview-icon">🔄</div>
                    <div class="preview-text">Changes Applied</div>
                    <div class="changes-list">${changesHtml}</div>
                    <div class="preview-subtext">Click "Update Now" to apply</div>
                </div>
            `;
        },

        async generateIconPackPreview() {
            return await this.generateModifiedWeatherPreview();
        },

        createPreviewImage(src, title) {
            const img = document.createElement('img');
            img.src = src;
            img.alt = title;
            img.style.cssText = 'max-width: 100%; max-height: 100px; object-fit: contain; border-radius: 4px; cursor: pointer; transition: transform 0.2s ease;';
            img.className = 'live-preview-clickable';
            img.title = 'Click to view full size';

            img.addEventListener('mouseenter', () => {
                img.style.transform = 'scale(1.05)';
            });
            img.addEventListener('mouseleave', () => {
                img.style.transform = 'scale(1)';
            });
            img.addEventListener('click', () => {
                this.openImageLightbox(src, title);
            });

            return img;
        },

        async generateModifiedWeatherPreview() {
            try {
                const form = document.getElementById('settingsForm');
                if (!form) return null;

                const formData = new FormData(form);
                formData.append('plugin_id', 'weather');

                const response = await fetch('/plugin/weather/icon_preview', {
                    method: 'POST',
                    body: formData,
                });

                if (!response.ok) {
                    console.warn('Weather preview API call failed:', response.status);
                    return null;
                }

                const blob = await response.blob();
                if (this._lastPreviewBlobUrl) {
                    URL.revokeObjectURL(this._lastPreviewBlobUrl);
                }
                const imageUrl = URL.createObjectURL(blob);
                this._lastPreviewBlobUrl = imageUrl;

                return imageUrl;
            } catch (error) {
                console.warn('Error generating weather preview:', error);
                return null;
            }
        },

        applyPreviewStyles(imgElement) {
            const formData = new FormData(document.getElementById('settingsForm'));

            const bgColor = formData.get('backgroundColor');
            if (bgColor && bgColor !== '#ffffff') {
                imgElement.style.backgroundColor = bgColor;
                imgElement.style.padding = '4px';
            }

            const topMargin = formData.get('topMargin');
            const bottomMargin = formData.get('bottomMargin');
            const leftMargin = formData.get('leftMargin');
            const rightMargin = formData.get('rightMargin');

            if (topMargin || bottomMargin || leftMargin || rightMargin) {
                const margins = `${topMargin || 0}px ${rightMargin || 0}px ${bottomMargin || 0}px ${leftMargin || 0}px`;
                imgElement.style.padding = margins;
                imgElement.style.border = '1px dashed var(--muted)';
            }

            const selectedFrame = formData.get('selectedFrame');
            if (selectedFrame && selectedFrame !== 'None') {
                switch (selectedFrame) {
                    case 'Rectangle':
                        imgElement.style.border = '2px solid var(--text)';
                        break;
                    case 'Top and Bottom':
                        imgElement.style.borderTop = '2px solid var(--text)';
                        imgElement.style.borderBottom = '2px solid var(--text)';
                        break;
                    case 'Corner':
                        imgElement.style.position = 'relative';
                        imgElement.style.borderRadius = '4px';
                        break;
                }
            }

            const textColor = formData.get('textColor');
            if (textColor && textColor !== '#000000') {
                imgElement.style.filter = `sepia(1) hue-rotate(${this.getHueFromColor(textColor)}deg)`;
            }
        },

        getHueFromColor(hexColor) {
            const r = parseInt(hexColor.substr(1, 2), 16);
            const g = parseInt(hexColor.substr(3, 2), 16);
            const b = parseInt(hexColor.substr(5, 2), 16);

            const max = Math.max(r, g, b);
            const min = Math.min(r, g, b);
            let hue;

            if (max === min) {
                hue = 0;
            } else {
                const d = max - min;
                switch (max) {
                    case r: hue = (g - b) / d + (g < b ? 6 : 0); break;
                    case g: hue = (b - r) / d + 2; break;
                    case b: hue = (r - g) / d + 4; break;
                }
                hue /= 6;
            }

            return Math.round(hue * 360);
        },

        openImageLightbox(imageSrc, title) {
            let lightboxModal = document.querySelector('.live-preview-lightbox');
            if (!lightboxModal) {
                lightboxModal = this.createLightboxModal();
                document.body.appendChild(lightboxModal);
            }

            const lightboxImg = lightboxModal.querySelector('.lightbox-image');
            const lightboxTitle = lightboxModal.querySelector('.lightbox-title');

            lightboxImg.src = imageSrc;
            lightboxTitle.textContent = title;

            lightboxModal.style.display = 'flex';
            requestAnimationFrame(() => {
                lightboxModal.classList.add('show');
            });
        },

        openModifiedImageLightbox(modifiedImg) {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');

            canvas.width = modifiedImg.naturalWidth || 400;
            canvas.height = modifiedImg.naturalHeight || 300;

            const tempImg = new Image();
            tempImg.crossOrigin = 'anonymous';
            tempImg.onload = () => {
                ctx.drawImage(tempImg, 0, 0, canvas.width, canvas.height);
                this.applyCanvasStyles(ctx, canvas, modifiedImg);
                const dataURL = canvas.toDataURL('image/png');
                this.openImageLightbox(dataURL, 'Preview with Changes');
            };
            tempImg.src = modifiedImg.src;
        },

        applyCanvasStyles(ctx, canvas, imgElement) {
            if (imgElement.style.backgroundColor && imgElement.style.backgroundColor !== 'transparent') {
                ctx.fillStyle = imgElement.style.backgroundColor;
                ctx.fillRect(0, 0, canvas.width, canvas.height);
            }

            if (imgElement.style.border || imgElement.style.borderTop || imgElement.style.borderBottom) {
                ctx.strokeStyle = '#333';
                ctx.lineWidth = 2;

                if (imgElement.style.border && imgElement.style.border.includes('solid')) {
                    ctx.strokeRect(0, 0, canvas.width, canvas.height);
                } else if (imgElement.style.borderTop) {
                    ctx.beginPath();
                    ctx.moveTo(0, 0);
                    ctx.lineTo(canvas.width, 0);
                    ctx.stroke();
                }
                if (imgElement.style.borderBottom) {
                    ctx.beginPath();
                    ctx.moveTo(0, canvas.height);
                    ctx.lineTo(canvas.width, canvas.height);
                    ctx.stroke();
                }
            }
        },

        createLightboxModal() {
            const modal = document.createElement('div');
            modal.className = 'live-preview-lightbox';
            modal.innerHTML = `
                <div class="lightbox-backdrop"></div>
                <div class="lightbox-container">
                    <div class="lightbox-header">
                        <h3 class="lightbox-title">Preview</h3>
                        <button class="lightbox-close" aria-label="Close">&times;</button>
                    </div>
                    <div class="lightbox-content">
                        <img class="lightbox-image" alt="Preview" />
                    </div>
                </div>
            `;

            const closeBtn = modal.querySelector('.lightbox-close');
            const backdrop = modal.querySelector('.lightbox-backdrop');

            const closeLightbox = () => {
                modal.classList.remove('show');
                setTimeout(() => {
                    modal.style.display = 'none';
                }, 300);
            };

            closeBtn.addEventListener('click', closeLightbox);
            backdrop.addEventListener('click', closeLightbox);

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && modal.style.display === 'flex') {
                    closeLightbox();
                }
            });

            return modal;
        },
    };

    window.InkyPiProgressiveDisclosure = root;
}());

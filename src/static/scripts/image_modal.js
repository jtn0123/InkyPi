document.addEventListener('DOMContentLoaded', function() {
    const imageContainer = document.querySelector('.image-container');
    if (!imageContainer) return;
    const img = imageContainer.querySelector('img');
    let modalOverlay = null;
    let modalImg = null;
    let observer = null;

    if (!img) return;

    // Handle click on image to show modal
    img.addEventListener('click', function(e) {
        e.stopPropagation();
        
        // Create overlay with image
        modalOverlay = document.createElement('div');
        modalOverlay.className = 'image-modal-overlay';
        
        modalImg = document.createElement('img');
        modalImg.src = img.src;
        modalOverlay.appendChild(modalImg);
        
        document.body.appendChild(modalOverlay);
        imageContainer.classList.add('maximized');
        document.body.style.overflow = 'hidden';
        
        // Observe original image for src changes
        observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.attributeName === 'src' && modalImg) {
                    modalImg.src = img.src;
                }
            });
        });
        
        observer.observe(img, { attributes: true, attributeFilter: ['src'] });
    });

    function closeModal() {
        if (observer) {
            observer.disconnect();
            observer = null;
        }
        if (modalOverlay) {
            modalOverlay.remove();
            modalOverlay = null;
        }
        modalImg = null;
        imageContainer.classList.remove('maximized');
        document.body.style.overflow = '';
    }

    // Handle click on overlay to close modal
    document.addEventListener('click', function(e) {
        if (imageContainer.classList.contains('maximized') && modalOverlay && !img.contains(e.target)) {
            closeModal();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && imageContainer.classList.contains('maximized')) {
            closeModal();
        }
    });

    window.addEventListener('beforeunload', closeModal);
});

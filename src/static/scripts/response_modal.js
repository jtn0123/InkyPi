// Function to Show the Response Modal
function showResponseModal(status, message) {
    const modal = document.getElementById('responseModal');
    const modalContent = document.getElementById('modalContent');
    const modalMessage = document.getElementById('modalMessage');

    // Remove any previous status classes
    modal.classList.remove('success', 'failure');

    // Add the correct class based on the status
    if (status === 'success') {
        modal.classList.add('success'); // Apply success class
    } else {
        modal.classList.add('failure'); // Apply failure class
    }
    modalMessage.textContent = message;

    // Display Modal
    modal.style.display = 'block';

    // Auto-Close Modal After 10 Seconds
    setTimeout(() => closeResponseModal(), 10000);
}

// Function to Close the Modal
function closeResponseModal() {
    const modal = document.getElementById('responseModal');
    modal.style.display = 'none';
}

/**
 * Parse a fetch Response and surface a uniform modal for success/error.
 * Returns the parsed JSON object for further handling if needed.
 */
async function handleJsonResponse(response) {
    let data = null;
    try {
        data = await response.json();
    } catch (e) {
        // Non-JSON responses
        if (!response.ok) {
            showResponseModal('failure', 'Request failed');
        }
        return null;
    }
    if (!response.ok || (data && data.success === false) || data?.error) {
        const rid = data && data.request_id ? ` (id: ${data.request_id})` : '';
        const msg = (data && (data.error || data.message)) || 'Request failed';
        showResponseModal('failure', `Error!  ${msg}${rid}`);
    } else {
        const rid = data && data.request_id ? ` (id: ${data.request_id})` : '';
        const msg = (data && data.message) || 'Success';
        showResponseModal('success', `Success! ${msg}${rid}`);
    }
    return data;
}

document.addEventListener("DOMContentLoaded", function () {
    const passwordFields = document.querySelectorAll(
        'input[name="password"], input[name="confirm_password"]'
    );

    passwordFields.forEach(function (field) {
        field.addEventListener("input", function () {
            field.setCustomValidity("");
        });
    });

    const signupForm = document.querySelector(
        'form input[name="confirm_password"]'
    );

    if (signupForm) {
        const form = signupForm.closest("form");

        form.addEventListener("submit", function (event) {
            const password = form.querySelector(
                'input[name="password"]'
            ).value;

            const confirmPassword = form.querySelector(
                'input[name="confirm_password"]'
            ).value;

            if (password !== confirmPassword) {
                event.preventDefault();
                signupForm.setCustomValidity("Passwords do not match.");
                signupForm.reportValidity();
            }
        });
    }
});
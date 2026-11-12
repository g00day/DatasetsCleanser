<template>
    <div class="auth-layout">
        <header class="auth-header">
            <RouterLink to="/" class="brand">
                DatasetsCleanser
            </RouterLink>
        </header>

        <main class="auth-main">
            <section class="auth-card">
                <slot />
            </section>
        </main>
    </div>
</template>
<script setup>

</script>


<template>
    <div class="project-layout">
        <header class="project-header">
            <RouterLink to="/project" class="brand">
                DatasetsCleanser
            </RouterLink>
            <div class="user-header">
                <button class="user-btn">
                    <img src="" alt="">
                    <p>username</p>
                </button>    
            </div>
        </header>
        <main class="project-main">
            <slot />
        </main>
    </div>
</template>
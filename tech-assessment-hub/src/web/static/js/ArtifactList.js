/**
 * ArtifactList — Reusable artifact list with class filter.
 *
 * Usage:
 *   var al = new ArtifactList({
 *       apiUrl: '/api/assessments/5/artifacts',
 *       instanceId: 2,
 *       bodyId: 'artifactBody',
 *       emptyId: 'artifactEmpty',
 *       loadingId: 'artifactLoading',
 *       metaId: 'artifactMeta',
 *       filterId: 'artifactClassFilter',
 *       badgeId: 'artifactsTabBadge',
 *   });
 *   al.refresh();
 */
window.ArtifactList = (function () {
    'use strict';

    function ArtifactList(opts) {
        this.apiUrl = opts.apiUrl;
        this.instanceId = opts.instanceId;
        this.bodyId = opts.bodyId;
        this.emptyId = opts.emptyId;
        this.loadingId = opts.loadingId;
        this.metaId = opts.metaId;
        this.filterId = opts.filterId;
        this.badgeId = opts.badgeId || null;
    }

    ArtifactList.prototype.setLoading = function (isLoading) {
        var overlay = document.getElementById(this.loadingId);
        if (overlay) overlay.style.display = isLoading ? 'flex' : 'none';
    };

    ArtifactList.prototype.renderRows = function (rows) {
        var tbody = document.getElementById(this.bodyId);
        var empty = document.getElementById(this.emptyId);
        if (!tbody || !empty) return;

        if (!rows.length) {
            tbody.innerHTML = '';
            empty.classList.remove('is-hidden');
            return;
        }

        empty.classList.add('is-hidden');
        var instanceId = this.instanceId;
        tbody.innerHTML = rows.map(function (row) {
            var updated = typeof formatDate === 'function' ? formatDate(row.sys_updated_on) : (row.sys_updated_on || '-');
            var active = row.active === true || row.active === 'true' ? 'Yes'
                : row.active === false || row.active === 'false' ? 'No' : '-';
            return '<tr>'
                + '<td><a href="/artifacts/' + row.sys_class_name + '/' + row.sys_id + '?instance_id=' + instanceId + '">' + (row.name || row.sys_id) + '</a></td>'
                + '<td>' + (row.class_label || row.sys_class_name || '-') + '</td>'
                + '<td>' + active + '</td>'
                + '<td>' + (row.sys_scope || '-') + '</td>'
                + '<td>' + updated + '</td>'
                + '<td><a class="btn btn-sm" href="/artifacts/' + row.sys_class_name + '/' + row.sys_id + '?instance_id=' + instanceId + '">View</a></td>'
                + '</tr>';
        }).join('');
    };

    ArtifactList.prototype.refresh = function () {
        var self = this;
        var meta = document.getElementById(this.metaId);
        var classFilter = document.getElementById(this.filterId);
        if (!classFilter) return;

        this.setLoading(true);
        if (meta) meta.textContent = 'Loading...';

        var params = new URLSearchParams({ limit: '500' });
        if (classFilter.value) params.set('sys_class_name', classFilter.value);

        fetch(this.apiUrl + '?' + params.toString(), { cache: 'no-store' })
            .then(function (r) { if (!r.ok) throw new Error('fail'); return r.json(); })
            .then(function (payload) {
                var classes = payload.classes || [];
                var currentVal = classFilter.value;
                classFilter.innerHTML = '<option value="">All Classes</option>';
                classes.forEach(function (cls) {
                    var opt = document.createElement('option');
                    opt.value = cls.sys_class_name;
                    opt.textContent = cls.label + ' (' + cls.count + ')';
                    classFilter.appendChild(opt);
                });
                if (currentVal) classFilter.value = currentVal;

                self.renderRows(payload.artifacts || []);

                if (self.badgeId) {
                    var badge = document.getElementById(self.badgeId);
                    if (badge) badge.textContent = String(payload.total || 0);
                }
                if (meta) meta.textContent = 'Showing ' + (payload.artifacts || []).length + ' of ' + (payload.total || 0) + ' artifacts';
            })
            .catch(function () {
                self.renderRows([]);
                if (meta) meta.textContent = 'Failed to load artifacts.';
            })
            .finally(function () {
                self.setLoading(false);
            });
    };

    ArtifactList.prototype.bindControls = function (applyId, resetId) {
        var self = this;
        var filter = document.getElementById(this.filterId);
        var apply = document.getElementById(applyId);
        var reset = document.getElementById(resetId);

        if (apply) apply.addEventListener('click', function () { self.refresh(); });
        if (filter) filter.addEventListener('change', function () { self.refresh(); });
        if (reset) reset.addEventListener('click', function () {
            if (filter) filter.value = '';
            self.refresh();
        });
    };

    return ArtifactList;
})();
